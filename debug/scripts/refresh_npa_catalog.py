"""Перезагрузить `npa_docs` из каталога All_marked_docs в SQLite."""
from __future__ import annotations

import sys

from paths import project_root


def main() -> None:
    root = project_root()
    sys.path.insert(0, str(root))

    from reg_monitor.npa_catalog import build_catalog_from_all_marked_docs
    from reg_monitor.settings import Settings
    from reg_monitor.state import StateStore

    s = Settings.from_env()
    docs = build_catalog_from_all_marked_docs(s.rag_norm_marked_docs_dir)
    StateStore(s.state_db_path).upsert_npa_docs(docs)
    print("upserted", len(docs), "into", s.state_db_path)


if __name__ == "__main__":
    main()
