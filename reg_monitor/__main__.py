from __future__ import annotations

import argparse
import json
import logging
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .excel_registry import ExcelRegistry
from .logging_setup import setup_logging
from .matching import Matcher
from .projects_source import iter_projects
from .qdrant_chunks_npa import build_npa_catalog_from_qdrant_chunks
from .npa_catalog import NpaDoc, build_catalog_from_all_marked_docs
from .settings import Settings
from .state import StateStore

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _write_run_metrics(settings: Settings, payload: dict) -> None:
    p = Path(settings.run_metrics_json_path)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        logger.info("Run metrics written to %s", p)
    except OSError as e:
        logger.warning("Could not write run metrics (%s): %s", p, e)


def run_once(settings: Settings) -> int:
    now = _utcnow()
    t_started = time.perf_counter()
    npas_qdrant = build_npa_catalog_from_qdrant_chunks(settings.rag_norm_qdrant_chunks)

    state = StateStore(settings.state_db_path)
    excel = ExcelRegistry(settings.excel_path)

    try:
        # Справочник НПА: структура из All_marked_docs (тип, номер, дата, орган) + номера из qdrant_chunks
        npa_marked: list[NpaDoc] = []
        try:
            npa_marked = build_catalog_from_all_marked_docs(settings.rag_norm_marked_docs_dir)
            state.upsert_npa_docs(npa_marked)
            logger.info(
                "NPA catalog refreshed: %d marked docs (matching uses marked + qdrant names)",
                len(npa_marked),
            )
        except Exception as e:
            logger.warning("Failed to refresh NPA catalog: %s", e)

        matcher = Matcher.from_sources(marked_docs=npa_marked, qdrant_npas=npas_qdrant)

        processed = 0
        matched = 0
        new_projects = 0
        run_highlight_color = excel.next_highlight_color()

        portal_from_date = None
        portal_max_date = None
        if settings.source in ("portal", "regulation", "regulation_gov", "regulation-gov"):
            raw_portal_date = state.get_kv("portal_last_creation_date")
            if raw_portal_date:
                try:
                    portal_from_date = datetime.fromisoformat(raw_portal_date).date()
                    logger.info("Portal source incremental scan from creationDate >= %s", portal_from_date)
                except ValueError:
                    logger.warning("Ignoring invalid portal_last_creation_date=%r", raw_portal_date)
            if portal_from_date is None:
                portal_from_date = (now.date() - timedelta(days=365 * 3))
                logger.info("Portal source initial scan from creationDate >= %s", portal_from_date)

        try:
            for pr in iter_projects(
                source=settings.source,
                max_items_per_run=settings.max_items_per_run,
                portal_from_date=portal_from_date,
            ):
                processed += 1
                if pr.date is not None and (
                    portal_max_date is None or pr.date > portal_max_date
                ):
                    portal_max_date = pr.date
                mr = matcher.match(pr)
                if mr.matched_docs:
                    matched += 1

                existed_before = state.get_project(pr.id_project) is not None
                is_new_in_excel = not excel.has_project(pr.id_project)
                changes = state.upsert_project(row=pr, match=mr, now=now)
                ts = state.get_project_timestamps(pr.id_project)
                if ts is None:
                    first_seen_at, last_seen_at, last_changed_at = now.isoformat(), now.isoformat(), None
                else:
                    first_seen_at, last_seen_at, last_changed_at = ts

                excel.upsert(
                    row=pr,
                    match=mr,
                    first_seen_at=first_seen_at,
                    last_seen_at=last_seen_at,
                    last_changed_at=last_changed_at,
                    highlight_color=run_highlight_color if is_new_in_excel else None,
                )
                if is_new_in_excel:
                    new_projects += 1
                if changes:
                    excel.append_history(changes)

                is_new = not existed_before
                if is_new or changes:
                    logger.debug("Project updated: id=%s new=%s changes=%d", pr.id_project, is_new, len(changes))

                iv = settings.progress_log_every
                if iv > 0 and processed % iv == 0:
                    excel.save()
                    logger.info("Progress: processed=%d matched=%d new=%d", processed, matched, new_projects)
        except Exception as e:
            # Сохраняем то, что успели, и завершаемся с кодом ошибки
            excel.save()
            logger.exception("run_once aborted after processed=%d due to error: %s", processed, e)
            elapsed = round(time.perf_counter() - t_started, 2)
            _write_run_metrics(
                settings,
                {
                    "status": "error",
                    "error": repr(e),
                    "finished_at_utc": _utcnow().isoformat(),
                    "elapsed_sec": elapsed,
                    "processed": processed,
                    "matched_projects": matched,
                    "new_projects": new_projects,
                    "highlight_color": run_highlight_color if new_projects else None,
                    "npa_marked_count": len(npa_marked),
                    "portal_last_creation_date": portal_max_date.isoformat() if portal_max_date else None,
                },
            )
            return 1

        excel.save()
        if portal_max_date is not None:
            state.set_kv("portal_last_creation_date", portal_max_date.isoformat())
        elapsed = round(time.perf_counter() - t_started, 2)
        _write_run_metrics(
            settings,
            {
                "status": "ok",
                "finished_at_utc": _utcnow().isoformat(),
                "elapsed_sec": elapsed,
                "processed": processed,
                "matched_projects": matched,
                "new_projects": new_projects,
                "highlight_color": run_highlight_color if new_projects else None,
                "npa_marked_count": len(npa_marked),
                "portal_last_creation_date": portal_max_date.isoformat() if portal_max_date else None,
                "checkpoint_note": (
                    "portal source reads from portal_last_creation_date; new Excel rows "
                    "are highlighted with the run color"
                ),
            },
        )
        logger.info(
            "Done. processed=%d matched=%d new=%d highlight=%s metrics=%s",
            processed,
            matched,
            new_projects,
            run_highlight_color if new_projects else None,
            settings.run_metrics_json_path,
        )
        return 0
    finally:
        state.close()


def main() -> int:
    ap = argparse.ArgumentParser(prog="reg_monitor")
    ap.add_argument("--once", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--dry-run", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--source", default=None, help="Project source: portal (default: env PROJECT_SOURCE)")
    args = ap.parse_args()

    setup_logging()
    settings = Settings.from_env(source=args.source)

    return run_once(settings)


if __name__ == "__main__":
    raise SystemExit(main())

