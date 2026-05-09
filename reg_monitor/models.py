from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime


@dataclass(frozen=True)
class NpaRef:
    doc_name: str
    doc_type: str | None
    doc_number: str | None
    doc_date: date | None


@dataclass(frozen=True)
class ProjectRow:
    # identity
    id_project: int
    title: str

    # stage/status
    stage: str | None = None
    status: str | None = None
    publish_date: date | None = None
    date: date | None = None
    start_discussion: date | None = None
    end_discussion: date | None = None

    # attributes
    creator_department: str | None = None
    creator_department_real: str | None = None
    category: str | None = None
    kind: str | None = None
    degree_regulatory_impact: str | None = None

    # flags
    published: bool | None = None
    region_significant: bool | None = None
    control_supervisory_activities: bool | None = None
    regulator_scissors: bool | None = None

    # computed
    link: str | None = None


@dataclass(frozen=True)
class MatchResult:
    matched_docs: list[str]
    score: float
    explain: str


@dataclass(frozen=True)
class ChangeEvent:
    ts: datetime
    id_project: int
    field: str
    old: str | None
    new: str | None

