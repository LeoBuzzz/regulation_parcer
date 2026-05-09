from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Iterable

from .models import ChangeEvent, MatchResult, ProjectRow


SCHEMA_SQL = """\
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS kv (
  k TEXT PRIMARY KEY,
  v TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS npa_docs (
  doc_key TEXT PRIMARY KEY,
  doc_type TEXT,
  doc_number TEXT,
  doc_date TEXT,
  approving_body TEXT,
  title TEXT NOT NULL,
  source_path TEXT NOT NULL,
  doc_display_name TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS projects (
  id_project INTEGER PRIMARY KEY,
  title TEXT NOT NULL,
  stage TEXT,
  status TEXT,
  publish_date TEXT,
  date TEXT,
  start_discussion TEXT,
  end_discussion TEXT,
  creator_department TEXT,
  creator_department_real TEXT,
  category TEXT,
  kind TEXT,
  degree_regulatory_impact TEXT,
  published INTEGER,
  region_significant INTEGER,
  control_supervisory_activities INTEGER,
  regulator_scissors INTEGER,
  link TEXT,
  matched_docs TEXT,
  match_score REAL,
  match_explain TEXT,
  first_seen_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL,
  last_changed_at TEXT
);

CREATE TABLE IF NOT EXISTS history (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL,
  id_project INTEGER NOT NULL,
  field TEXT NOT NULL,
  old TEXT,
  new TEXT
);
"""


def ensure_npa_docs_schema(conn: sqlite3.Connection) -> None:
    """Добавить колонки к существующим БД (CREATE IF NOT EXISTS их не добавляет)."""
    cols = {row[1] for row in conn.execute("PRAGMA table_info(npa_docs)")}
    if "approving_body" not in cols:
        conn.execute("ALTER TABLE npa_docs ADD COLUMN approving_body TEXT")
        conn.commit()


def _dt_iso(dt: datetime) -> str:
    return dt.replace(microsecond=0).isoformat()


def _d_iso(d) -> str | None:
    if d is None:
        return None
    return str(d)


def _b_int(v) -> int | None:
    if v is None:
        return None
    return 1 if bool(v) else 0


class StateStore:
    def __init__(self, db_path: str | Path):
        self.path = Path(db_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path))
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA_SQL)
        ensure_npa_docs_schema(self.conn)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def get_project(self, id_project: int):
        cur = self.conn.execute("SELECT * FROM projects WHERE id_project=?", (id_project,))
        return cur.fetchone()

    def upsert_project(
        self,
        *,
        row: ProjectRow,
        match: MatchResult,
        now: datetime,
    ) -> list[ChangeEvent]:
        prev = self.get_project(row.id_project)
        now_s = _dt_iso(now)

        changes: list[ChangeEvent] = []
        if prev is not None:
            # Track only stage/status changes (per requirements)
            old_stage = prev["stage"]
            old_status = prev["status"]
            new_stage = row.stage
            new_status = row.status
            if (old_stage or "") != (new_stage or ""):
                changes.append(ChangeEvent(ts=now, id_project=row.id_project, field="Stage", old=old_stage, new=new_stage))
            if (old_status or "") != (new_status or ""):
                changes.append(ChangeEvent(ts=now, id_project=row.id_project, field="Status", old=old_status, new=new_status))

        matched_docs_json = json.dumps(match.matched_docs, ensure_ascii=False)

        if prev is None:
            self.conn.execute(
                """
                INSERT INTO projects (
                  id_project,title,stage,status,publish_date,date,start_discussion,end_discussion,
                  creator_department,creator_department_real,category,kind,degree_regulatory_impact,
                  published,region_significant,control_supervisory_activities,regulator_scissors,link,
                  matched_docs,match_score,match_explain,first_seen_at,last_seen_at,last_changed_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    row.id_project,
                    row.title,
                    row.stage,
                    row.status,
                    _d_iso(row.publish_date),
                    _d_iso(row.date),
                    _d_iso(row.start_discussion),
                    _d_iso(row.end_discussion),
                    row.creator_department,
                    row.creator_department_real,
                    row.category,
                    row.kind,
                    row.degree_regulatory_impact,
                    _b_int(row.published),
                    _b_int(row.region_significant),
                    _b_int(row.control_supervisory_activities),
                    _b_int(row.regulator_scissors),
                    row.link,
                    matched_docs_json,
                    match.score,
                    match.explain,
                    now_s,
                    now_s,
                    now_s if changes else None,
                ),
            )
        else:
            last_changed_at = prev["last_changed_at"]
            if changes:
                last_changed_at = now_s
                for ev in changes:
                    self.conn.execute(
                        "INSERT INTO history (ts,id_project,field,old,new) VALUES (?,?,?,?,?)",
                        (_dt_iso(ev.ts), ev.id_project, ev.field, ev.old, ev.new),
                    )
            self.conn.execute(
                """
                UPDATE projects SET
                  title=?,
                  stage=?, status=?,
                  publish_date=?, date=?, start_discussion=?, end_discussion=?,
                  creator_department=?, creator_department_real=?,
                  category=?, kind=?, degree_regulatory_impact=?,
                  published=?, region_significant=?, control_supervisory_activities=?, regulator_scissors=?,
                  link=?,
                  matched_docs=?, match_score=?, match_explain=?,
                  last_seen_at=?, last_changed_at=?
                WHERE id_project=?
                """,
                (
                    row.title,
                    row.stage,
                    row.status,
                    _d_iso(row.publish_date),
                    _d_iso(row.date),
                    _d_iso(row.start_discussion),
                    _d_iso(row.end_discussion),
                    row.creator_department,
                    row.creator_department_real,
                    row.category,
                    row.kind,
                    row.degree_regulatory_impact,
                    _b_int(row.published),
                    _b_int(row.region_significant),
                    _b_int(row.control_supervisory_activities),
                    _b_int(row.regulator_scissors),
                    row.link,
                    matched_docs_json,
                    match.score,
                    match.explain,
                    now_s,
                    last_changed_at,
                    row.id_project,
                ),
            )

        self.conn.commit()
        return changes

    def get_project_timestamps(self, id_project: int) -> tuple[str, str, str | None] | None:
        r = self.get_project(id_project)
        if r is None:
            return None
        return (r["first_seen_at"], r["last_seen_at"], r["last_changed_at"])

    def get_kv(self, key: str) -> str | None:
        cur = self.conn.execute("SELECT v FROM kv WHERE k=?", (key,))
        row = cur.fetchone()
        return None if row is None else str(row[0])

    def set_kv(self, key: str, value: str) -> None:
        self.conn.execute(
            "INSERT INTO kv (k,v) VALUES (?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
            (key, value),
        )
        self.conn.commit()

    def upsert_npa_docs(self, docs) -> None:
        self.conn.execute("DELETE FROM npa_docs")
        self.conn.executemany(
            """
            INSERT INTO npa_docs (doc_key,doc_type,doc_number,doc_date,approving_body,title,source_path,doc_display_name)
            VALUES (?,?,?,?,?,?,?,?)
            """,
            [
                (
                    d.doc_key,
                    d.doc_type,
                    d.doc_number,
                    (d.doc_date.isoformat() if d.doc_date else None),
                    (d.approving_body.strip() if d.approving_body else None),
                    d.title or "",
                    d.source_path,
                    d.doc_display_name,
                )
                for d in docs
            ],
        )
        self.conn.commit()

