from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from reg_monitor.state import ensure_npa_docs_schema

from paths import state_db_path


def main() -> None:
    conn = sqlite3.connect(str(state_db_path()))
    try:
        ensure_npa_docs_schema(conn)
        rows = conn.execute(
            """
            SELECT doc_type, doc_number, doc_date, approving_body, title, source_path FROM npa_docs
            WHERE doc_type IS NULL OR doc_type = ''
               OR doc_number IS NULL OR doc_number = ''
               OR doc_date IS NULL OR doc_date = ''
               OR approving_body IS NULL OR approving_body = ''
            ORDER BY source_path
            """
        ).fetchall()
        print("gaps", len(rows))
        for row in rows:
            print("---")
            print(row[-1])
            print(row)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
