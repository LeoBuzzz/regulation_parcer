from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Iterator

from dateutil import parser as date_parser


_WS_RE = re.compile(r"\s+")
_NUM_GENERIC_RE = re.compile(
    r"(?:\bN\b|№|n)\s*([0-9]+(?:[-–][0-9]+)*(?:[-–][А-Яа-яA-Za-zёЁ0-9]{1,12})?|[0-9]+(?:[-–]ФЗ|[-–]\s*ФЗ))",
    re.IGNORECASE,
)
_GOST_RE = re.compile(r"\bГОСТ\b\s*(?:Р\b\s*)?([0-9]+(?:\.[0-9]+)*[-–][0-9]{2,4})", re.IGNORECASE)
_RD_DESIGNATION_RE = re.compile(r"\bРД\b\s+([0-9]+(?:\.[0-9]+)*-\d{2,4})", re.IGNORECASE)
_INTRODUCTION_DATE_RE = re.compile(r"Дата введения\s+(\d{4})-(\d{2})-(\d{2})", re.IGNORECASE)
_DATE_DMY_RE = re.compile(r"\b(\d{1,2})[._/ ](\d{1,2})[._/ ](\d{2,4})\b")
_DATE_DMY_UNDERSCORE_RE = re.compile(r"\b(\d{1,2})_(\d{1,2})_(\d{2,4})\b")
_RU_MONTHS = {
    "января": 1,
    "февраля": 2,
    "марта": 3,
    "апреля": 4,
    "мая": 5,
    "июня": 6,
    "июля": 7,
    "августа": 8,
    "сентября": 9,
    "октября": 10,
    "ноября": 11,
    "декабря": 12,
}
_DATE_RU_RE = re.compile(r"\b(\d{1,2})\s+([а-яё]+)\s+(\d{4})\s+года\b", re.IGNORECASE)
_HASH_BALANCED_TITLE_RE = re.compile(r"^\s*(#{1,6})\s*(.+?)\s*\1\s*$")
_SKIP_HEADING_INNER_EXACT = frozenset(
    {
        "ПРИКАЗ",
        "РАСПОРЯЖЕНИЕ",
        "ПОСТАНОВЛЕНИЕ",
        "ФЕДЕРАЛЬНЫЙ ЗАКОН",
        "РОССИЙСКАЯ ФЕДЕРАЦИЯ",
    }
)
_GOST_ACCEPT_RE = re.compile(
    r"ПРИНЯТ\s+([^\n]+?)\s*\(протокол",
    re.IGNORECASE,
)
_GOST_ACCEPT_SHORT_RE = re.compile(
    r"ПРИНЯТ\s+([^\n]+)$",
    re.IGNORECASE | re.MULTILINE,
)
_RD_EES_RE = re.compile(
    r"Российск(?:ого|ое)\s+акционер(?:ного|ное)\s+общества\s+[^.\n]*[«\"]ЕЭС\s+России[»\"]",
    re.IGNORECASE,
)


def _norm_spaces(s: str) -> str:
    return _WS_RE.sub(" ", s.replace("_", " ").strip())


def _sanitize_calendar_date(dt: date | None) -> date | None:
    if dt is None:
        return None
    y = dt.year
    if y < 1900 or y > date.today().year + 5:
        return None
    return dt


def _parse_introduction_date(text_raw: str) -> date | None:
    if not text_raw:
        return None
    m = _INTRODUCTION_DATE_RE.search(text_raw)
    if not m:
        return None
    y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    try:
        return date(y, mo, d)
    except ValueError:
        return None


def is_pue_marked_fragment(path: Path) -> bool:
    """Отдельные главы ПУЭ в этом корпусе — не включаем в справочник НПА."""
    n = path.stem.lower()
    return "правила устройства электроустановок" in n and "(пуэ)" in n


def _filename_kind(stem_lower: str) -> str | None:
    sl = stem_lower.strip()
    if sl.startswith("распоряжение "):
        return "rasp"
    if sl.startswith("рд "):
        return "rd"
    return None


def _parse_date_from_text(text_raw: str) -> date | None:
    if not text_raw:
        return None

    d_intro = _parse_introduction_date(text_raw)
    if d_intro:
        return _sanitize_calendar_date(d_intro)

    m = _DATE_DMY_UNDERSCORE_RE.search(text_raw)
    if m:
        dd, mm, yy = m.group(1), m.group(2), m.group(3)
        try:
            return _sanitize_calendar_date(date(int(yy), int(mm), int(dd)))
        except Exception:
            pass

    text = _norm_spaces(text_raw)
    m = _DATE_DMY_RE.search(text)
    if m:
        dd, mm, yy = m.group(1), m.group(2), m.group(3)
        raw = f"{dd}.{mm}.{yy}"
        try:
            return _sanitize_calendar_date(date_parser.parse(raw, dayfirst=True).date())
        except Exception:
            pass

    m = _DATE_RU_RE.search(text.lower())
    if m:
        dd, mon, yy = m.group(1), m.group(2), m.group(3)
        mon_i = _RU_MONTHS.get(mon.lower())
        if mon_i:
            try:
                return _sanitize_calendar_date(date(int(yy), int(mon_i), int(dd)))
            except Exception:
                pass

    return None


def _gost_edition_year_from_designation(designation: str | None) -> int | None:
    if not designation:
        return None
    s = designation.replace("–", "-").strip()
    m = re.search(r"-(\d{4})$", s)
    if not m:
        return None
    y = int(m.group(1))
    if 1970 <= y <= date.today().year + 3:
        return y
    return None


def _iter_hash_headings(head: str, *, max_lines: int = 55) -> Iterator[str]:
    for line in head.splitlines()[:max_lines]:
        m = _HASH_BALANCED_TITLE_RE.match(line.strip())
        if not m:
            continue
        inner = _norm_spaces(m.group(2)).strip()
        if not inner:
            continue
        yield inner


def _heading_org_candidate(inner_u: str) -> bool:
    if inner_u in _SKIP_HEADING_INNER_EXACT:
        return False
    if inner_u.startswith("ОБ ") or inner_u.startswith("Об "):
        return False
    if re.match(r"^ОТ \d", inner_u):
        return False
    keys = (
        "МИНИСТЕРСТВО",
        "ПРАВИТЕЛЬСТВО",
        "ФЕДЕРАЛЬН",
        "СЛУЖБА",
        "АГЕНТСТВО",
        "КОМИТЕТ",
        "РОСТЕХНАДЗОР",
        "РОСТАНДАРТ",
        "РОССТАНДАРТ",
        "НАДЗОР",
        "ДУМА",
        "СОВЕТ ФЕДЕРАЦИИ",
        "КОНСТИТУЦИОННЫЙ СУД",
        "ВЕРХОВНЫЙ СУД",
        "РОСРЕЕСТР",
        "РОСЭНЕРГОНАДЗОР",
        "РОСРИВЕДЕНИЕ",
        "РОСИМУЩЕСТВО",
        "РОСЛЕСХОЗ",
        "РОСЗДРАВНАДЗОР",
        "РОСРЕПОТРАБЗОР",
        "ЦЕНТРОБАНК",
        "БАНК РОССИИ",
    )
    return any(k in inner_u for k in keys)


def _parse_body_from_headings(head: str) -> str | None:
    for inner in _iter_hash_headings(head):
        inn_u = inner.upper()
        if not _heading_org_candidate(inn_u):
            continue
        return inner
    return None


def _parse_gost_accepted_by(head: str) -> str | None:
    m = _GOST_ACCEPT_RE.search(head)
    if m:
        s = _norm_spaces(m.group(1)).strip(" \\")
        if "межгосударствен" in s.lower() and "совет" in s.lower():
            return "Межгосударственный совет по стандартизации, метрологии и сертификации (МГС)"
        return s
    # редкая разметка без «(протокол»
    m = _GOST_ACCEPT_SHORT_RE.search(head)
    if m:
        s = _norm_spaces(m.group(1)).strip(" \\")
        if len(s) > 14 and ("совет" in s.lower() or "межгосударствен" in s.lower()):
            if "межгосударствен" in s.lower():
                return "Межгосударственный совет по стандартизации, метрологии и сертификации (МГС)"
            return s
    return None


def _parse_rd_approving_body(head: str) -> str | None:
    """Руководящие документы нередко утверждаются отраслевым Советом РАО «ЕЭС России» и др."""
    m = _RD_EES_RE.search(head)
    if m:
        return 'Российское акционерное общество "ЕЭС России" (Научно-технический Совет)'
    return None


def _parse_fz_federal_assembly(head: str) -> str | None:
    hl = head.lower()
    if "принят" in hl and "государственной дум" in hl:
        return "Федеральное Собрание Российской Федерации"
    if "*** принят ***" in hl and "дума" in hl:
        return "Федеральное Собрание Российской Федерации"
    return None


def _is_weak_catalog_title(title: str) -> bool:
    u = _norm_spaces(title).strip("#* ").upper()
    if len(u) < 6:
        return True
    if u in {"РОССИЙСКАЯ ФЕДЕРАЦИЯ", "РОССИЙСКАЯ ФЕДЕРАЦИЯ #"}:
        return True
    if u == "ПРАВИТЕЛЬСТВО РОССИЙСКОЙ ФЕДЕРАЦИИ":
        return True
    return False


def _title_from_stem_fallback(name_norm: str) -> str | None:
    """Тематика из имени файла после номера («N … О/Об …»)."""
    m = re.search(r"\b[Nn№]\s*\S+\s+(.+)$", name_norm)
    if m:
        t = m.group(1).strip()
        return t if len(t) > 5 else None
    return None


def parse_approving_body(head: str, *, doc_type: str | None) -> str | None:
    head_n = head or ""

    if doc_type == "ГОСТ":
        g = _parse_gost_accepted_by(head_n)
        if g:
            return g
        return "Межгосударственный совет по стандартизации, метрологии и сертификации (МГС)"

    if doc_type == "РД":
        r = _parse_rd_approving_body(head_n)
        if r:
            return r
        return _parse_body_from_headings(head_n)

    if doc_type in ("ФЗ", "Кодекс"):
        fa = _parse_fz_federal_assembly(head_n)
        if fa:
            return fa
        h = _parse_body_from_headings(head_n)
        if h:
            return h
        return "Федеральное Собрание Российской Федерации"

    h = _parse_body_from_headings(head_n)
    if h:
        return h

    if doc_type in ("Постановление", "Распоряжение"):
        if re.search(r"правительств[ао]\s+российской\s+федерации", head_n, re.I):
            return "Правительство Российской Федерации"

    return None


def parse_doc_number(text: str, *, kind: str | None = None) -> str | None:
    mg = _GOST_RE.search(text)
    if mg:
        return _norm_spaces(mg.group(1)).replace("–", "-").upper()
    if kind == "rd":
        mr = _RD_DESIGNATION_RE.search(text.replace("–", "-"))
        if mr:
            return mr.group(1).replace("–", "-").upper()
    if kind == "rasp":
        mr = _NUM_GENERIC_RE.search(text.replace("–", "-"))
        if mr:
            return _norm_spaces(mr.group(1)).replace("–", "-").upper()
        return None
    m = _NUM_GENERIC_RE.search(text.replace("–", "-"))
    if not m:
        return None
    return _norm_spaces(m.group(1)).replace("–", "-").upper()


def parse_doc_type(text: str, *, stem_lower: str | None = None) -> str | None:
    stem = stem_lower or ""
    if stem.startswith("распоряжение "):
        return "Распоряжение"
    if stem.startswith("постановление "):
        return "Постановление"
    if stem.startswith("приказ "):
        return "Приказ"
    if stem.startswith("рд "):
        return "РД"
    if stem.startswith("гост ") or stem.startswith("гост р "):
        return "ГОСТ"
    if stem.startswith("закон "):
        return "ФЗ"
    if stem.startswith("кодекс "):
        return "Кодекс"
    if "правила устройства электроустановок" in stem and "(пуэ)" in stem:
        return None
    t = text.lower()
    if "федеральный закон" in t or " фз " in f" {t} ":
        return "ФЗ"
    if "гост" in t:
        return "ГОСТ"
    if "распоряжение" in t:
        return "Распоряжение"
    if "постановление" in t:
        return "Постановление"
    if "приказ" in t:
        return "Приказ"
    if "кодекс" in t:
        return "Кодекс"
    return None


@dataclass(frozen=True)
class NpaDoc:
    doc_key: str
    doc_type: str | None
    doc_number: str | None
    doc_date: date | None
    approving_body: str | None
    title: str
    source_path: str

    @property
    def doc_display_name(self) -> str:
        parts = []
        if self.doc_type:
            parts.append(self.doc_type)
        if self.doc_date:
            parts.append(self.doc_date.isoformat())
        if self.doc_number:
            parts.append(f"№ {self.doc_number}")
        if self.approving_body:
            parts.append(self.approving_body)
        if self.title:
            parts.append(self.title)
        return " ".join(parts).strip()


def parse_marked_doc(path: Path, *, read_head_lines: int = 40) -> NpaDoc:
    name = path.stem
    name_norm = _norm_spaces(name)
    stem_l = name_norm.lower()

    head = ""
    try:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            for _ in range(read_head_lines):
                line = f.readline()
                if not line:
                    break
                head += line
    except OSError:
        head = ""

    head_norm = _norm_spaces(head)

    kind = _filename_kind(stem_l)
    doc_type = parse_doc_type(name_norm, stem_lower=stem_l) or parse_doc_type(head_norm, stem_lower=stem_l)

    if kind == "rd":
        doc_number = parse_doc_number(name_norm, kind=kind) or parse_doc_number(head_norm, kind=kind)
        doc_date = _parse_date_from_text(name) or _parse_date_from_text(head)
    elif kind == "rasp":
        doc_number = parse_doc_number(name_norm, kind=kind) or parse_doc_number(head_norm, kind=kind)
        doc_date = _parse_date_from_text(name) or _parse_date_from_text(head)
    else:
        doc_number = parse_doc_number(name_norm) or parse_doc_number(head_norm)
        doc_date = _parse_date_from_text(name) or _parse_date_from_text(head)

    if doc_type == "ГОСТ" and doc_date is None:
        y_from_std = _gost_edition_year_from_designation(doc_number)
        if y_from_std is not None:
            doc_date = _sanitize_calendar_date(date(y_from_std, 1, 1))
        if doc_date is None:
            doc_date = _parse_introduction_date(head)

    approving_body = parse_approving_body(head, doc_type=doc_type)

    title = ""
    m = re.search(r"\bОб\b\s+(.+)$", name_norm)
    if m:
        title = m.group(1).strip()
    else:
        for line in head.splitlines():
            s = line.strip().strip("#* ").strip()
            if not s:
                continue
            if len(s) < 6:
                continue
            if "переход к содержанию" in s.lower():
                continue
            title = s
            break

    fb = _title_from_stem_fallback(name_norm)
    if _is_weak_catalog_title(title) and fb:
        title = fb
    elif approving_body and _norm_spaces(title).upper() == _norm_spaces(approving_body).upper() and fb:
        title = fb

    doc_key = "|".join(
        [
            (doc_type or "").upper(),
            (doc_number or "").upper(),
            (doc_date.isoformat() if doc_date else ""),
            name_norm.lower(),
        ]
    )

    return NpaDoc(
        doc_key=doc_key,
        doc_type=doc_type,
        doc_number=doc_number,
        doc_date=doc_date,
        approving_body=approving_body,
        title=title,
        source_path=str(path),
    )


def build_catalog_from_all_marked_docs(dir_path: str | Path) -> list[NpaDoc]:
    d = Path(dir_path)
    files = sorted(d.glob("*.txt"), key=lambda p: p.name.lower())
    docs: list[NpaDoc] = []
    for p in files:
        if is_pue_marked_fragment(p):
            continue
        docs.append(parse_marked_doc(p))
    return docs
