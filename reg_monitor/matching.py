from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import date

from .models import MatchResult, ProjectRow
from .npa_catalog import NpaDoc
from .qdrant_chunks_npa import NpaParsed

# Номер после № / N / n (в т.ч. 903н, 162-Р)
_NUM_AFTER_MARK_RE = re.compile(
    r"(?:\bN\b|№|n)\s*"
    r"([0-9]+(?:[./][0-9]+)*(?:[-–][0-9]+(?:[./][0-9]+)*)?(?:[-–][А-Яа-яA-Za-zёЁ0-9]{1,12})?)",
    re.IGNORECASE,
)
_GOST_RE = re.compile(r"\bГОСТ\b\s*(?:Р\b\s*)?([0-9]+(?:\.[0-9]+)*[-–][0-9]{2,4})", re.IGNORECASE)
# Без явного №: 35-ФЗ, 188-ФЗ в середине заголовка
_STANDALONE_FZ_RE = re.compile(r"\b(\d+[-–]ФЗ)\b", re.IGNORECASE)
# Цифра + кириллический хвост: 903н
_NUM_CYR_SUFFIX_RE = re.compile(r"\b(\d{1,6})([А-Яа-яёЁ]{1,4})\b")

_CHANGE_MARKERS = (
    "внести изменения",
    "о внесении изменений",
    "изменения в",
    "признать утратившим силу",
    "признании утратившим силу",
    "разработка изменений",
)

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

_DATE_PART_RE = (
    r"(?:\d{1,2}[._/]\d{1,2}[._/]\d{2,4}"
    r"|\d{1,2}\s+[А-Яа-яёЁ]+\s+\d{4}\s*(?:г\.?|года)?)"
)
_DOC_REF_RE = re.compile(
    r"(?P<type>"
    r"постановлени(?:ем|е|я)|"
    r"приказ(?:ом|ы|а)?|"
    r"распоряжени(?:ем|е|я)|"
    r"указ(?:а|ом)?|"
    r"федеральн(?:ый|ого|ым)\s+закон(?:а|ом)?|"
    r"закон(?:а|ом)?|"
    r"кодекс(?:а|ом)?|"
    r"ГОСТ(?:\s+Р)?"
    r")"
    r"(?P<body>.{0,160}?)"
    r"\s+от\s+(?P<date>" + _DATE_PART_RE + r")"
    r".{0,40}?(?:№|\bN\b|номер)\s*(?P<number>"
    r"[0-9]+(?:[./][0-9]+)*(?:[-–][0-9]+(?:[./][0-9]+)*)?(?:[-–][А-Яа-яA-Za-zёЁ0-9]{1,12})?"
    r")",
    re.IGNORECASE | re.DOTALL,
)
_STOP_BODY_RE = re.compile(
    r"\b(утвержденн(?:ые|ый|ое|ая|ым|ого|ной)|в\s+редакции|о\s+внесении|об\s+утверждении)\b",
    re.IGNORECASE,
)
_BODY_CLEAN_PREFIX_RE = re.compile(
    r"^[\s,.;:«\"'()]+|[\s,.;:»\"'()]+$",
    re.IGNORECASE,
)
_BODY_ALIASES = {
    "минэнерго": "министерство энергетики российской федерации",
    "минтруд": "министерство труда и социальной защиты российской федерации",
    "минтранса": "министерство транспорта российской федерации",
    "минтранс": "министерство транспорта российской федерации",
    "минобрнауки": "министерство образования и науки российской федерации",
    "минприроды": "министерство природных ресурсов и экологии российской федерации",
    "минпромторг": "министерство промышленности и торговли российской федерации",
    "минстрой": "министерство строительства и жилищно-коммунального хозяйства российской федерации",
    "минздрав": "министерство здравоохранения российской федерации",
    "минюст": "министерство юстиции российской федерации",
    "мчс": "министерство российской федерации по делам гражданской обороны чрезвычайным ситуациям",
    "фст": "федеральная служба по тарифам",
    "ростехнадзор": "федеральная служба по экологическому технологическому и атомному надзору",
    "банк россии": "центральный банк российской федерации",
    "центральный банк российской федерации": "центральный банк российской федерации",
}
_BODY_STOP_TOKENS = {
    "и",
    "по",
    "при",
    "для",
    "на",
    "о",
    "об",
    "в",
    "во",
    "россии",
    "российской",
    "российская",
    "российский",
    "российского",
    "федерации",
    "федеральная",
    "федеральной",
    "федеральный",
    "федерального",
    "служба",
    "службы",
    "министерство",
    "министерства",
}


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.replace("–", "-").strip().lower())


def _norm_number(s: str | None) -> str | None:
    if not s:
        return None
    raw = s.replace("–", "-").replace(" ", "").upper()
    if "ФЗ" not in raw and re.search(r"\d+N$", raw):
        raw = raw[:-1] + "Н"
    return raw or None


def _norm_type(s: str | None) -> str | None:
    if not s:
        return None
    low = _norm(s).replace("ё", "е")
    if "гост" in low:
        return "ГОСТ"
    if "федераль" in low and "закон" in low:
        return "ФЗ"
    if low.startswith("закон"):
        return "ФЗ"
    if low.startswith("постановлен"):
        return "Постановление"
    if low.startswith("приказ"):
        return "Приказ"
    if low.startswith("распоряжен"):
        return "Распоряжение"
    if low.startswith("указ"):
        return "Указ"
    if low.startswith("кодекс"):
        return "Кодекс"
    if low.startswith("рд"):
        return "РД"
    return None


def _parse_ru_date(raw: str | None) -> date | None:
    if not raw:
        return None
    s = _norm(raw).replace("_", ".").replace("/", ".")
    m = re.search(r"\b(\d{1,2})\.(\d{1,2})\.(\d{2,4})\b", s)
    if m:
        dd, mm, yy = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if yy < 100:
            yy += 2000 if yy < 70 else 1900
        try:
            return date(yy, mm, dd)
        except ValueError:
            return None
    m = re.search(r"\b(\d{1,2})\s+([а-яё]+)\s+(\d{4})\b", s, re.IGNORECASE)
    if m:
        mon = _RU_MONTHS.get(m.group(2).lower())
        if mon:
            try:
                return date(int(m.group(3)), mon, int(m.group(1)))
            except ValueError:
                return None
    return None


def _clean_body(raw: str | None) -> str | None:
    if not raw:
        return None
    s = _norm(raw).replace("ё", "е")
    # For phrases like "в приказ Министерства..." the prefix belongs to grammar, not the body.
    s = re.sub(r"^(?:\s+|в|во|к|ко|из|в\s+редакции)\s+", "", s)
    m = _STOP_BODY_RE.search(s)
    if m:
        s = s[: m.start()]
    s = _BODY_CLEAN_PREFIX_RE.sub("", s)
    s = re.sub(r"\s+", " ", s)
    return s or None


def _body_canonical(raw: str | None) -> str | None:
    s = _clean_body(raw)
    if not s:
        return None
    s = s.replace("рф", "российской федерации")
    s = re.sub(r"\bправительств[аоем]*\s+российской\s+федерации\b", "правительство российской федерации", s)
    for alias, canon in _BODY_ALIASES.items():
        if alias in s:
            return canon
    s = re.sub(r"\s+", " ", s)
    return s or None


def _body_tokens(raw: str | None) -> set[str]:
    canon = _body_canonical(raw)
    if not canon:
        return set()
    out: set[str] = set()
    for token in re.findall(r"[а-яёa-z0-9]+", canon.lower()):
        if len(token) < 3 or token in _BODY_STOP_TOKENS:
            continue
        out.add(token)
    return out


def _body_matches(a: str | None, b: str | None) -> bool:
    ca = _body_canonical(a)
    cb = _body_canonical(b)
    if not ca or not cb:
        return False
    if ca == cb or ca in cb or cb in ca:
        return True
    ta = _body_tokens(ca)
    tb = _body_tokens(cb)
    if not ta or not tb:
        return False
    return len(ta & tb) / max(len(ta), len(tb)) >= 0.6


@dataclass(frozen=True)
class ProjectDocRef:
    doc_type: str | None
    doc_number: str
    doc_date: date | None
    approving_body: str | None


@dataclass(frozen=True)
class CatalogDoc:
    label: str
    doc_type: str | None
    doc_number: str | None
    doc_date: date | None
    approving_body: str | None


def _extract_structured_refs(text: str) -> list[ProjectDocRef]:
    refs: list[ProjectDocRef] = []
    seen: set[tuple[str | None, str, date | None, str | None]] = set()
    for m in _DOC_REF_RE.finditer(text.replace("–", "-")):
        number = _norm_number(m.group("number"))
        if not number:
            continue
        ref = ProjectDocRef(
            doc_type=_norm_type(m.group("type")),
            doc_number=number,
            doc_date=_parse_ru_date(m.group("date")),
            approving_body=_body_canonical(m.group("body")),
        )
        key = (ref.doc_type, ref.doc_number, ref.doc_date, ref.approving_body)
        if key not in seen:
            refs.append(ref)
            seen.add(key)
    return refs


def expanded_catalog_number_keys(doc_number: str | None) -> set[str]:
    """Ключи по номеру из каталога НПА — совпадают с тем, как номер может встретиться у проекта."""
    if not doc_number:
        return set()
    raw = doc_number.replace("–", "-").replace(" ", "").upper()
    out: set[str] = {raw}

    if re.match(r"^\d+[А-ЯЁ]{1,6}$", raw):
        m = re.match(r"^(\d+)", raw)
        if m:
            out.add(m.group(1))

    parts = raw.split("-")
    if len(parts) >= 2:
        tail = parts[-1]
        if re.fullmatch(r"[А-ЯЁ]{1,8}", tail) and tail != "ФЗ":
            prefix = "-".join(parts[:-1])
            if prefix:
                out.add(prefix)
        if tail == "ФЗ":
            out.add("-".join(parts[:-1]) + "-" + tail)

    return {k for k in out if k}


def _extract_numbers(title: str) -> set[str]:
    t = title.replace("–", "-")
    out: set[str] = set()

    for m in _NUM_AFTER_MARK_RE.finditer(t):
        grp = m.group(1)
        if not grp:
            continue
        s = grp.replace("–", "-").replace(" ", "").upper()
        if "ФЗ" not in s and re.search(r"\d+N$", s):
            s = s[:-1] + "Н"
        if s:
            out.add(s)

    # «903 n» / «903-N» как приказы с литерой латинским n → нормализуем под каталог №903н
    for m in re.finditer(r"\b(\d{1,6})\s*[-.]?\s*([NnнН])(?!\w)", t):
        base = m.group(1)
        out.add(base)
        suf = m.group(2).upper().replace("N", "Н")
        if suf == "Н":
            out.add(f"{base}Н")

    for m in _STANDALONE_FZ_RE.finditer(t):
        out.add(m.group(1).replace("–", "-").upper())

    for m in _NUM_CYR_SUFFIX_RE.finditer(t):
        num, suf = m.group(1), m.group(2).upper()
        if suf in ("ФЗ", "Ф", "ФЗЯ"):
            continue
        out.add(f"{num}{suf}")
        if len(suf) <= 6:
            out.add(num)

    mg = _GOST_RE.search(t)
    if mg:
        out.add(mg.group(1).replace("–", "-").upper())

    return {x for x in out if any(c.isdigit() for c in x)}


def expanded_query_keys(nums: set[str]) -> list[str]:
    agg: list[str] = []
    seen: set[str] = set()
    for raw in nums:
        for key in expanded_catalog_number_keys(raw) | {raw.replace(" ", "").upper()}:
            if key not in seen:
                seen.add(key)
                agg.append(key)
        if raw not in seen:
            ru = raw.replace(" ", "").upper()
            if ru not in seen:
                seen.add(ru)
                agg.append(ru)
    return agg


def _marked_catalog_index(
    marked: list[NpaDoc],
) -> dict[str, list[CatalogDoc]]:
    idx: dict[str, list[CatalogDoc]] = defaultdict(list)
    for d in marked:
        cdoc = CatalogDoc(
            label=d.doc_display_name,
            doc_type=_norm_type(d.doc_type),
            doc_number=_norm_number(d.doc_number),
            doc_date=d.doc_date,
            approving_body=d.approving_body,
        )
        for key in expanded_catalog_number_keys(d.doc_number):
            idx[key].append(cdoc)
    return dict(idx)


def _qdrant_catalog_index(npas: list[NpaParsed]) -> dict[str, list[CatalogDoc]]:
    idx: dict[str, list[CatalogDoc]] = defaultdict(list)
    for n in npas:
        if not n.doc_number:
            continue
        cdoc = CatalogDoc(
            label=n.doc_name,
            doc_type=_norm_type(n.doc_type),
            doc_number=_norm_number(n.doc_number),
            doc_date=n.doc_date,
            approving_body=None,
        )
        for key in expanded_catalog_number_keys(n.doc_number):
            idx[key].append(cdoc)
    return dict(idx)


def _merge_catalog_index(*indexes: dict[str, list[CatalogDoc]]) -> dict[str, list[CatalogDoc]]:
    merged: dict[str, list[CatalogDoc]] = defaultdict(list)
    seen_by_key: dict[str, set[str]] = defaultdict(set)
    for idx in indexes:
        for key, docs in idx.items():
            for doc in docs:
                if doc.label in seen_by_key[key]:
                    continue
                seen_by_key[key].add(doc.label)
                merged[key].append(doc)
    return dict(merged)


def _score_structured_ref(ref: ProjectDocRef, doc: CatalogDoc) -> tuple[int, list[str]]:
    score = 0
    parts: list[str] = []
    if _norm_number(doc.doc_number) == ref.doc_number:
        score += 1
        parts.append("number")
    if ref.doc_type and doc.doc_type and ref.doc_type == doc.doc_type:
        score += 1
        parts.append("type")
    if ref.doc_date and doc.doc_date and ref.doc_date == doc.doc_date:
        score += 1
        parts.append("date")
    if ref.approving_body and doc.approving_body and _body_matches(ref.approving_body, doc.approving_body):
        score += 1
        parts.append("body")
    return score, parts


@dataclass(frozen=True)
class Matcher:
    """
    Заголовок проекта парсится в структурные ссылки на НПА. Для идентификации
    используются только вид, номер, дата и утвердивший орган; название документа
    в сравнении не участвует.
    """

    _number_index: dict[str, list[CatalogDoc]]
    min_score: float = 0.45

    @staticmethod
    def from_sources(
        *,
        marked_docs: list[NpaDoc],
        qdrant_npas: list[NpaParsed],
        min_score: float = 0.45,
    ) -> Matcher:
        idx = _merge_catalog_index(
            _marked_catalog_index(marked_docs),
            _qdrant_catalog_index(qdrant_npas),
        )
        return Matcher(_number_index=idx, min_score=min_score)

    def match(self, project: ProjectRow) -> MatchResult:
        title = project.title or ""
        t_norm = _norm(title)
        refs = _extract_structured_refs(title)

        matched: list[str] = []
        explain: list[str] = []
        score = 0.0
        idx = self._number_index

        for ref in refs:
            keys = expanded_query_keys({ref.doc_number})
            best_for_ref: list[tuple[int, CatalogDoc, list[str]]] = []
            seen_labels: set[str] = set()
            for key in keys:
                for doc in idx.get(key, []):
                    if doc.label in seen_labels:
                        continue
                    seen_labels.add(doc.label)
                    s, parts = _score_structured_ref(ref, doc)
                    # A bare number is too ambiguous; even number+type+body produced false
                    # positives. Require the act date as the second hard key,
                    # plus either document type or approving body.
                    if "number" in parts and "date" in parts and ("type" in parts or "body" in parts):
                        best_for_ref.append((s, doc, parts))
            if not best_for_ref:
                continue
            best_score = max(s for s, _, _ in best_for_ref)
            for s, doc, parts in best_for_ref:
                if s != best_score:
                    continue
                matched.append(doc.label)
                score += float(s)
                explain.append(f"struct:{ref.doc_number}:{'+'.join(parts)}")

        if matched and any(m in t_norm for m in _CHANGE_MARKERS):
            score += 0.35
            explain.append("chg")

        matched_uniq = sorted(set(matched))
        final = min(25.0, score)
        if final < self.min_score:
            return MatchResult(matched_docs=[], score=float(final), explain="low_score")
        return MatchResult(
            matched_docs=matched_uniq,
            score=float(final),
            explain=";".join(explain[:14]) or "match",
        )
