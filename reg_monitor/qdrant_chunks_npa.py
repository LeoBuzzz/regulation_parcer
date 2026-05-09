from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Iterable, Iterator

import ijson
from dateutil import parser as date_parser

logger = logging.getLogger(__name__)


_WS_RE = re.compile(r"\s+")
_DOC_TYPE_RE = re.compile(
    r"\b(приказ|постановление|закон|федеральный\s+закон|распоряжение|указ|письмо|гост)\b",
    re.IGNORECASE,
)
_DOC_NUMBER_RE = re.compile(
    r"(?:\bN\b|№)\s*([0-9]+(?:\s*[-–]\s*[0-9]+)?(?:\s*[-–]\s*[А-Яа-яA-Za-zёЁ]{1,12})?"
    r"|[0-9]+[-–]ФЗ)",
    re.IGNORECASE,
)
_GOST_NUMBER_RE = re.compile(
    r"\bГОСТ\b\s*(?:Р\b\s*)?([0-9]+(?:\.[0-9]+)*[-–][0-9]{2,4})",
    re.IGNORECASE,
)
_DATE_RE = re.compile(r"\b(\d{1,2}[./]\d{1,2}[./]\d{2,4})\b")


def _norm_spaces(s: str) -> str:
    return _WS_RE.sub(" ", s.replace("_", " ").strip())


def _parse_date_from_doc_name(doc_name: str) -> date | None:
    m = _DATE_RE.search(doc_name)
    if not m:
        return None
    raw = m.group(1)
    try:
        dt = date_parser.parse(raw, dayfirst=True).date()
        return dt
    except Exception:
        return None


def _parse_doc_type(doc_name: str) -> str | None:
    m = _DOC_TYPE_RE.search(doc_name)
    if not m:
        return None
    t = m.group(1).lower()
    t = _norm_spaces(t)
    if t == "федеральный закон":
        return "ФЗ"
    if t == "гост":
        return "ГОСТ"
    return t.capitalize()


def _parse_doc_number(doc_name: str) -> str | None:
    mg = _GOST_NUMBER_RE.search(doc_name)
    if mg:
        return _norm_spaces(mg.group(1)).replace("–", "-").upper()
    m = _DOC_NUMBER_RE.search(doc_name)
    if not m:
        return None
    num = m.group(1)
    num = _norm_spaces(num).replace("–", "-")
    num = num.replace(" - ", "-").replace(" -", "-").replace("- ", "-")
    return num.upper()


@dataclass(frozen=True)
class NpaParsed:
    doc_name: str
    doc_type: str | None
    doc_number: str | None
    doc_date: date | None


def iter_unique_doc_names_from_qdrant_chunks(path: Path) -> Iterator[str]:
    """
    Потоково читает большой qdrant_chunks.json и отдаёт уникальные payload.doc_name.
    """
    seen: set[str] = set()
    with path.open("rb") as f:
        for payload in ijson.items(f, "item.payload"):
            if not isinstance(payload, dict):
                continue
            doc_name = payload.get("doc_name")
            if not doc_name or not isinstance(doc_name, str):
                doc_name = payload.get("filename")
            if not doc_name or not isinstance(doc_name, str):
                continue
            # filename может быть путём — берём последний компонент
            if "\\" in doc_name or "/" in doc_name:
                doc_name = doc_name.replace("\\", "/").rsplit("/", 1)[-1]
                if doc_name.lower().endswith(".txt") or doc_name.lower().endswith(".rtf"):
                    doc_name = doc_name.rsplit(".", 1)[0]

            doc_name = _norm_spaces(doc_name)
            if not doc_name or doc_name in seen:
                continue
            seen.add(doc_name)
            yield doc_name


def build_npa_catalog_from_qdrant_chunks(path: str | Path) -> list[NpaParsed]:
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(str(p))
    out: list[NpaParsed] = []
    for doc_name in iter_unique_doc_names_from_qdrant_chunks(p):
        out.append(
            NpaParsed(
                doc_name=doc_name,
                doc_type=_parse_doc_type(doc_name),
                doc_number=_parse_doc_number(doc_name),
                doc_date=_parse_date_from_doc_name(doc_name),
            )
        )
    logger.info("Extracted %d unique doc_name from %s", len(out), p)
    return out


def npa_number_index(npas: Iterable[NpaParsed]) -> dict[str, list[str]]:
    """
    Индекс: номер НПА -> список doc_name.
    """
    idx: dict[str, list[str]] = {}
    for n in npas:
        if not n.doc_number:
            continue
        idx.setdefault(n.doc_number, []).append(n.doc_name)
    return idx

