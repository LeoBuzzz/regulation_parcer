from __future__ import annotations

import logging
import time
from datetime import date
from typing import Any, Iterator

import requests
from dateutil import parser as date_parser
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .models import ProjectRow

logger = logging.getLogger(__name__)

BASE_URL = "https://regulation.gov.ru"
PROJECTS_API = f"{BASE_URL}/api/public/PublicProjects/GetFiltered"
PROJECT_CARD_URL = f"{BASE_URL}/projects/{{id_project}}/"

ORDERED_FIELDS = [
    "id",
    "title",
    "projectId",
    "creationDate",
    "publicationDate",
    "developedDepartment",
    "stage",
    "status",
    "procedure",
    "projectType",
    "startPublicDiscussion",
    "endPublicDiscussion",
]


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date_parser.parse(value).date()
    except Exception:
        return None


def _description(obj: Any) -> str | None:
    if isinstance(obj, dict):
        value = obj.get("description")
        return str(value).strip() if value else None
    if isinstance(obj, str):
        return obj.strip() or None
    return None


def _session() -> requests.Session:
    sess = requests.Session()
    retry = Retry(
        total=5,
        connect=5,
        read=5,
        backoff_factor=1.2,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET", "POST"),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    sess.mount("https://", adapter)
    sess.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
            ),
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
            "Content-Type": "application/json",
            "Origin": BASE_URL,
            "Referer": f"{BASE_URL}/projects/?type=ListView",
        }
    )
    # The portal sets a lightweight cookie on the HTML page; keep parity with browser flow.
    sess.get(f"{BASE_URL}/projects/?type=ListView", timeout=(10, 60))
    return sess


def _payload(*, page: int, page_size: int, filters: str) -> dict:
    return {
        "listParams": {
            "filterModel": {
                "filters": filters,
                "page": page,
                "pageSize": page_size,
                "sorts": "-creationDate",
            }
        },
        "orderedFields": ORDERED_FIELDS,
    }


def iter_projects_portal(
    *,
    max_items: int = 50000,
    from_date: date | None = None,
    page_size: int = 100,
    sleep_sec: float = 0.15,
) -> Iterator[ProjectRow]:
    """
    Live portal source. Uses the Next.js public endpoint behind regulation.gov.ru/projects.

    `from_date` narrows incremental daily runs via the site's own creationDate filter.
    """
    sess = _session()
    filters = f"creationDate>={from_date.isoformat()}" if from_date else ""
    yielded = 0
    page = 1
    total: int | None = None

    while yielded < max_items:
        payload = _payload(page=page, page_size=page_size, filters=filters)
        r = sess.post(PROJECTS_API, json=payload, timeout=(10, 90))
        if r.status_code != 200:
            logger.warning("Portal source non-200 at page=%s: %s %s", page, r.status_code, r.text[:300])
            break
        data = r.json()
        total = int(data.get("totalCount") or 0)
        items = data.get("result") or []
        if not items:
            break

        for item in items:
            raw_id = item.get("id")
            try:
                pid = int(raw_id)
            except Exception:
                continue
            title = str(item.get("title") or "").strip()
            if not title:
                continue
            department = _description(item.get("developedDepartment"))
            yield ProjectRow(
                id_project=pid,
                title=title,
                stage=str(item.get("stage") or "") or None,
                status=str(item.get("status") or "") or None,
                publish_date=_parse_date(item.get("publicationDate")),
                date=_parse_date(item.get("creationDate")),
                start_discussion=_parse_date(item.get("startPublicDiscussion")),
                end_discussion=_parse_date(item.get("endPublicDiscussion")),
                creator_department=department,
                creator_department_real=None,
                category=_description(item.get("procedure")),
                kind=_description(item.get("projectType")),
                degree_regulatory_impact=None,
                published=None,
                region_significant=None,
                control_supervisory_activities=None,
                regulator_scissors=None,
                link=PROJECT_CARD_URL.format(id_project=pid),
            )
            yielded += 1
            if yielded >= max_items:
                break

        if yielded >= max_items or page * page_size >= total:
            break
        page += 1
        if sleep_sec > 0:
            time.sleep(sleep_sec)

    logger.info("Fetched %d projects from regulation.gov.ru portal (total=%s, from_date=%s)", yielded, total, from_date)
