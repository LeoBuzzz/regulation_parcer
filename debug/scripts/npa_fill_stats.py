from __future__ import annotations

import sqlite3

from paths import state_db_path


def main() -> None:
    conn = sqlite3.connect(str(state_db_path()))
    try:
        row = conn.execute(
            """
            select
              count(*) as total,
              sum(case when doc_type is not null and doc_type<>'' then 1 else 0 end) as has_type,
              sum(case when doc_number is not null and doc_number<>'' then 1 else 0 end) as has_number,
              sum(case when doc_date is not null and doc_date<>'' then 1 else 0 end) as has_date,
              sum(case when approving_body is not null and approving_body<>'' then 1 else 0 end) as has_body,
              sum(case when title is not null and title<>'' then 1 else 0 end) as has_title,
              sum(case when doc_display_name is not null and doc_display_name<>'' then 1 else 0 end) as has_display
            from npa_docs
            """
        ).fetchone()
        print(
            "total",
            row[0],
            "has_type",
            row[1],
            "has_number",
            row[2],
            "has_date",
            row[3],
            "has_body",
            row[4],
            "has_title",
            row[5],
            "has_display",
            row[6],
        )
    finally:
        conn.close()


if __name__ == "__main__":
    main()
