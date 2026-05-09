from __future__ import annotations

from typing import Iterator

from .models import ProjectRow
from .regulation_portal_source import iter_projects_portal


def iter_projects(
    *,
    source: str,
    max_items_per_run: int,
    portal_from_date=None,
) -> Iterator[ProjectRow]:
    src = (source or "").strip().lower()
    if src in ("portal", "regulation", "regulation_gov", "regulation-gov"):
        yield from iter_projects_portal(max_items=max_items_per_run, from_date=portal_from_date)
        return

    raise ValueError(f"Unsupported project source: {source!r}. Use PROJECT_SOURCE=portal.")

