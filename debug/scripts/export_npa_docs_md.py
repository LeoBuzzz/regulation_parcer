"""Экспорт таблицы npa_docs в Markdown (debug/npa_docs_catalog.md)."""
from __future__ import annotations

import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from reg_monitor.state import ensure_npa_docs_schema

from paths import debug_dir, project_root, state_db_path


def _esc_cell(s: str | None, *, posix_slash_path: bool = False) -> str:
    if not s:
        return ""
    t = str(s).replace("|", "\\|").replace("\r\n", " ").replace("\n", " ").strip()
    return t.replace("\\", "/") if posix_slash_path else t


def main() -> None:
    root = project_root()
    db = state_db_path()
    out_path = debug_dir() / "npa_docs_catalog.md"

    conn = sqlite3.connect(str(db))
    try:
        ensure_npa_docs_schema(conn)
        rows = conn.execute(
            """
            SELECT doc_type, doc_number, doc_date, approving_body, title, source_path
            FROM npa_docs
            ORDER BY COALESCE(doc_type,''), COALESCE(doc_number,''), source_path
            """
        ).fetchall()
        stats = conn.execute(
            """
            SELECT count(*),
              sum(case when doc_type is not null and doc_type<>'' then 1 else 0 end),
              sum(case when doc_number is not null and doc_number<>'' then 1 else 0 end),
              sum(case when doc_date is not null and doc_date<>'' then 1 else 0 end),
              sum(case when approving_body is not null and approving_body<>'' then 1 else 0 end)
            FROM npa_docs
            """
        ).fetchone()
    finally:
        conn.close()

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    try:
        rel = db.relative_to(root).as_posix()
        db_rel = f"`{rel}` от корня проекта; абсолютный путь: `{db.as_posix()}`"
    except ValueError:
        db_rel = f"`{db.as_posix()}`"

    lines: list[str] = [
        "# Каталог документов `npa_docs`",
        "",
        f"Снимок сгенерирован: **{now}**",
        "",
        "Фрагменты **ПУЭ** (отдельные главы вида «Правила устройства электроустановок (ПУЭ). Глава …») в справочник **не входят**.",
        "",
        "Поля для поиска/матчинга: **вид документа**, **утвердивший орган**, **номер**, **дата**.",
        "",
        "## Где лежит база",
        "",
        f"- Файл SQLite: {db_rel}",
        "- Таблица: `npa_docs` (пересобирается из `All_marked_docs` при запуске `python -m reg_monitor --once` при заданном `RAG_NORM_MARKED_DOCS_DIR`; не меняет `rag_norm`).",
        "",
        "## Сводка",
        "",
        f"- Всего строк: **{stats[0]}**",
        f"- С типом: **{stats[1]}**",
        f"- С номером: **{stats[2]}**",
        f"- С датой: **{stats[3]}**",
        f"- С органом утверждения: **{stats[4]}**",
        "",
        "## Таблица документов",
        "",
        "| № | Тип | Утвердивший орган | Номер | Дата | Заголовок | Путь к файлу в корпусе |",
        "|---|-----|-------------------|-------|------|-----------|-------------------------|",
    ]

    for i, row in enumerate(rows, start=1):
        d_type, num, dt, body, title, src = row
        lines.append(
            "| "
            + " | ".join(
                (
                    str(i),
                    _esc_cell(d_type),
                    _esc_cell(body),
                    _esc_cell(num),
                    _esc_cell(dt),
                    _esc_cell(title),
                    _esc_cell(src, posix_slash_path=True),
                )
            )
            + " |"
        )

    lines.extend(
        [
            "",
            "---",
            "",
            "*Пересоздание после обновления БД:* `python debug/scripts/export_npa_docs_md.py`",
            "",
        ]
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")
    print("written", len(rows), "rows ->", out_path)


if __name__ == "__main__":
    main()
