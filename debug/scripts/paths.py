"""Пути к корню проекта и к SQLite (можно переопределить через STATE_DB_PATH)."""
from __future__ import annotations

import os
from pathlib import Path


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def state_db_path() -> Path:
    raw = (os.environ.get("STATE_DB_PATH") or "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return (project_root() / "data" / "state.sqlite3").resolve()


def debug_dir() -> Path:
    return project_root() / "debug"

