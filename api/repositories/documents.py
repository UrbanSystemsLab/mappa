"""Searching the plans, regulations and laws by meaning.

Each document is stored as passages (`document_chunks`) with an embedding. A
search embeds the query, finds the nearest passages, and keeps at most a couple
from any one document so a long plan cannot crowd out the rule that governs it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from core import MIN_RELEVANCE

from .. import db
from ..embeddings import vector

PER_DOCUMENT = 2
CANDIDATES_PER_RESULT = 5

# Island-wide documents apply to every municipio. The inventory marks them
# "N/A" or leaves the municipio blank.
_ISLAND_WIDE = "d.jurisdiction IS NULL OR d.jurisdiction IN ('', 'N/A', 'Puerto Rico')"

# La Maraña's inventory IDs, which a reader can look up on their sheet.
_INVENTORY_ID = re.compile(r"^(?:DOC|HMP|WCRP|RV|POT|GIS|TRA)-\d{2,4}(?:[.-]\d+)?$", re.I)

# Titles that are really file names - "TRA-030_Transit Plan Caguas 2024 (2)".
_CODE_PREFIX = re.compile(r"^[A-Z]{2,4}-\d{2,4}(?:\.\d+)?[_\s-]+(?=\S)")
_EXTENSION = re.compile(r"\.(?:pdf|docx?|xlsx?)\w*$", re.I)
_COPY = re.compile(r"\s*\(\d+\)\s*$")


@dataclass(frozen=True, slots=True)
class Passage:
    doc_id: str
    title: str
    year: int | None
    text: str
    score: float

    @property
    def reference(self) -> str:
        """Their inventory ID, or empty for a file not on their sheet."""
        return self.doc_id if _INVENTORY_ID.match(self.doc_id or "") else ""


def display_title(title: str) -> str:
    """A title as a reader should see it: file-name residue removed, nothing added."""
    t = _CODE_PREFIX.sub("", _COPY.sub("", _EXTENSION.sub("", (title or "").strip())))
    if t.count("-") >= 3 and " " not in t:
        t = t.replace("-", " ")
    return t.strip(" -_") or (title or "").strip()


def search(
    query: str, municipio: str | None = None, k: int = 6, only: list[int] | None = None
) -> list[Passage]:
    """The `k` passages nearest the query, from that municipio's documents and the
    island-wide ones. Given `only` - the documents that discuss a layer - from
    those alone, when any of them has a passage on the query. Below
    MIN_RELEVANCE a passage is not about the query."""
    lit = vector(query)
    sql = (
        "SELECT d.source_id, d.title, d.year, c.text, 1 - (c.embedding <=> %s::vector) "
        "FROM document_chunks c JOIN documents d ON d.id = c.document_id {where} "
        "ORDER BY c.embedding <=> %s::vector LIMIT %s"
    )
    limit = k * CANDIDATES_PER_RESULT
    place = f"(d.jurisdiction ILIKE %s OR {_ISLAND_WIDE})"
    tries: list[tuple[str, list]] = []
    if only and municipio:
        tries.append((f"WHERE c.document_id = ANY(%s) AND {place}", [only, municipio]))
    elif only:
        tries.append(("WHERE c.document_id = ANY(%s)", [only]))
    if municipio:
        tries.append((f"WHERE {place}", [municipio]))
    tries.append(("", []))
    with db.connection() as conn:
        cur = conn.cursor()
        # The vector index returns nearest-first and then filters; iterative
        # scan keeps going until enough rows pass the filter.
        cur.execute("SET LOCAL hnsw.iterative_scan = relaxed_order")
        rows = []
        for where, params in tries:
            cur.execute(sql.format(where=where), (lit, *params, lit, limit))
            rows = [r for r in cur.fetchall() if r[4] is not None and float(r[4]) >= MIN_RELEVANCE]
            if rows:
                break
    found = [
        Passage(doc_id, display_title(title), year, text, float(score))
        for doc_id, title, year, text, score in rows
    ]
    return spread(found, k)


def spread(passages: list[Passage], k: int) -> list[Passage]:
    """The best passages, at most PER_DOCUMENT from any one document."""
    taken: dict[str, int] = {}
    out = []
    for p in passages:
        if taken.get(p.doc_id, 0) < PER_DOCUMENT:
            taken[p.doc_id] = taken.get(p.doc_id, 0) + 1
            out.append(p)
            if len(out) == k:
                break
    return out
