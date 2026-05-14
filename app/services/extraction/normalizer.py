import re
from typing import Iterable, List

from app.schemas.paper import RetrievedPaper


VENUE_ALIASES: dict[str, tuple[str, ...]] = {
    "icml": ("icml", "international conference on machine learning"),
    "neurips": ("neurips", "nips", "conference on neural information processing systems", "advances in neural information processing systems"),
    "iclr": ("iclr", "international conference on learning representations"),
    "acl": ("acl", "annual meeting of the association for computational linguistics"),
    "emnlp": ("emnlp", "empirical methods in natural language processing"),
    "cvpr": ("cvpr", "computer vision and pattern recognition"),
    "iccv": ("iccv", "international conference on computer vision"),
    "eccv": ("eccv", "european conference on computer vision"),
    "aaai": ("aaai", "aaai conference on artificial intelligence"),
    "kdd": ("kdd", "knowledge discovery and data mining"),
}


def clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = re.sub(r"\s+", " ", value).strip()
    return cleaned or None


def normalize_title(value: str | None) -> str:
    value = clean_text(value) or ""
    value = re.sub(r"[^a-z0-9\s]", "", value.lower())
    return re.sub(r"\s+", " ", value).strip()


def _venue_terms(value: str | None) -> tuple[str, ...]:
    normalized = clean_text(value)
    if not normalized:
        return ()
    lowered = normalized.lower()
    aliases = VENUE_ALIASES.get(lowered)
    if aliases:
        return aliases
    return (lowered,)


_VENUE_PREFIX_RE = re.compile(
    r"^(proceedings of (the )?|the proceedings of (the )?|workshop at |workshops at |"
    r"\d+(st|nd|rd|th) |\d+(st|nd|rd|th) annual |annual )"
)
_VENUE_PARENS_RE = re.compile(r"\([^)]*\)")
_VENUE_TRAILING_YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")
_VENUE_NON_ALNUM_RE = re.compile(r"[^a-z0-9 ]+")
_VENUE_WS_RE = re.compile(r"\s+")


def _normalize_venue(value: str | None) -> str:
    cleaned = clean_text(value)
    if not cleaned:
        return ""
    text = cleaned.lower()
    text = _VENUE_PARENS_RE.sub(" ", text)
    text = _VENUE_TRAILING_YEAR_RE.sub(" ", text)
    # Iteratively peel off prefixes like "Proceedings of the 40th Annual"
    while True:
        new_text = _VENUE_PREFIX_RE.sub("", text, count=1)
        if new_text == text:
            break
        text = new_text
    text = _VENUE_NON_ALNUM_RE.sub(" ", text)
    text = _VENUE_WS_RE.sub(" ", text).strip()
    return text


def _matches_venue(paper_venue: str | None, target: str | None, *, strict: bool) -> bool:
    if not target:
        return True
    aliases = _venue_terms(target)
    if not aliases:
        return True
    normalized = _normalize_venue(paper_venue)
    if not normalized:
        return False
    if strict:
        return normalized in aliases
    return any(alias in normalized for alias in aliases)


def parse_year_filter(value: str | int | None) -> tuple[int | None, int | None]:
    if value is None:
        return None, None

    if isinstance(value, int):
        return value, value

    normalized = clean_text(value)
    if not normalized:
        return None, None

    if normalized.lower() in {"string", "none", "null", "undefined", "all", "any"}:
        return None, None

    exact_match = re.fullmatch(r"\d{4}", normalized)
    if exact_match:
        year = int(normalized)
        return year, year

    range_match = re.fullmatch(r"(\d{4})\s*-\s*(\d{4})", normalized)
    if range_match:
        return int(range_match.group(1)), int(range_match.group(2))

    raise ValueError(f"Unsupported year filter: {value}")


def filter_papers(
    papers: Iterable[RetrievedPaper],
    *,
    year: str | int | None = None,
    venue: str | None = None,
    strict_venue: bool = False,
) -> List[RetrievedPaper]:
    start_year, end_year = parse_year_filter(year)
    venue_filter_active = bool(clean_text(venue))
    results: List[RetrievedPaper] = []

    for paper in papers:
        if start_year is not None:
            if paper.year is None or paper.year < start_year or paper.year > (end_year or start_year):
                continue
        if venue_filter_active and not _matches_venue(paper.venue, venue, strict=strict_venue):
            continue
        results.append(paper)

    return results


def deduplicate_papers(papers: Iterable[RetrievedPaper]) -> List[RetrievedPaper]:
    priority = {"semantic_scholar": 4, "openalex": 3, "arxiv": 2, "tavily": 1}
    best_by_key: dict[str, RetrievedPaper] = {}

    for paper in papers:
        key = normalize_title(paper.title) or (paper.url or paper.external_id or "")
        if not key:
            continue

        existing = best_by_key.get(key)
        if existing is None:
            best_by_key[key] = paper
            continue

        if priority.get(paper.source, 0) > priority.get(existing.source, 0):
            best_by_key[key] = paper
            continue

        if existing.abstract is None and paper.abstract:
            best_by_key[key] = paper

    return list(best_by_key.values())
