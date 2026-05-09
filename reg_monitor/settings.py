from __future__ import annotations

import os
from dataclasses import dataclass


def _env(name: str, default: str | None = None) -> str | None:
    v = os.environ.get(name)
    if v is None:
        return default
    v = v.strip()
    return v if v else default


@dataclass(frozen=True)
class Settings:
    rag_norm_qdrant_chunks: str
    rag_norm_marked_docs_dir: str
    state_db_path: str
    excel_path: str
    max_items_per_run: int
    source: str
    progress_log_every: int
    run_metrics_json_path: str

    @staticmethod
    def from_env(*, source: str | None = None) -> "Settings":
        rag = _env("RAG_NORM_QDRANT_CHUNKS", r"C:\PY\PythonProject\rag_norm\qdrant_chunks.json")
        marked = _env("RAG_NORM_MARKED_DOCS_DIR", r"C:\PY\PythonProject\rag_norm\All_marked_docs")
        state = _env("STATE_DB_PATH", "./data/state.sqlite3")
        excel = _env("EXCEL_PATH", "./data/Output.xlsx")
        max_items = int(_env("MAX_ITEMS_PER_RUN", "50000") or "50000")
        src = (source or _env("PROJECT_SOURCE", "portal") or "portal").lower()
        prog_iv = max(50, int(_env("RUN_PROGRESS_INTERVAL", "2000") or "2000"))
        metrics_path = (
            _env("RUN_METRICS_JSON_PATH") or "./data/last_run_metrics.json"
        ).strip()
        return Settings(
            rag_norm_qdrant_chunks=rag,
            rag_norm_marked_docs_dir=marked,
            state_db_path=state,
            excel_path=excel,
            max_items_per_run=max_items,
            source=src,
            progress_log_every=prog_iv,
            run_metrics_json_path=metrics_path,
        )

