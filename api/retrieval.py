import json
import re
import unicodedata
from pathlib import Path
from typing import Any

import numpy as np
from sentence_transformers import SentenceTransformer

from core import EMBEDDING_MODEL as EMBEDDING_MODEL_NAME
from core import settings

# Their inventory IDs. A document they supplied that is not on the sheet gets an
# LM- slug from its filename, which is an internal key rather than a reference a
# reader could look up, so it is not shown as one.
_THEIR_ID = re.compile(r"^(?:DOC|HMP|WCRP|RV|POT|GIS)-\d{2,4}(?:-\d+)?$", re.I)


# Titles that are really file names - "TRA-030_Transit Plan Caguas 2024 (2)",
# "Barceloneta-Transportacion-Barceloneta-Informe-11-12-2022.docxII" - because
# that is what was typed into the inventory. Tidied for display only: the code
# prefix, the file extension and a copy marker are dropped, and hyphens between
# words become spaces. Nothing is added, and the stored title is unchanged.
_CODE_PREFIX = re.compile(r"^(?:[A-Z]{2,4}-\d{2,4}(?:\.\d+)?)[_\s-]+(?=\S)")
_EXTENSION = re.compile(r"\.(?:pdf|docx?|xlsx?)\w*$", re.I)
_COPY = re.compile(r"\s*\(\d+\)\s*$")


def display_title(title: str) -> str:
    t = (title or "").strip()
    t = _EXTENSION.sub("", t)
    t = _COPY.sub("", t)
    t = _CODE_PREFIX.sub("", t)
    if t.count("-") >= 3 and " " not in t:
        t = t.replace("-", " ")  # a file name: words joined by hyphens
    return t.strip(" -_") or (title or "").strip()


def citation_id(doc_id: str) -> str:
    return doc_id if _THEIR_ID.match(doc_id or "") else ""


DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATA_PATH = DATA_DIR / "documents.json"
# Extra local corpora merged in if present (e.g. documents pulled from Drive).
EXTRA_PATHS = [DATA_DIR / "planning_docs.json", DATA_DIR / "drive_docs.json"]


# When DATABASE_URL is set, retrieval runs against Cloud SQL (pgvector) over the full
# corpus; otherwise it falls back to the in-memory index over the local JSON corpus.
_query_model: SentenceTransformer | None = None


def _get_query_model() -> SentenceTransformer:
    global _query_model
    if _query_model is None:
        _query_model = SentenceTransformer(EMBEDDING_MODEL_NAME)
    return _query_model


def _vector_literal(vec: Any) -> str:
    return "[" + ",".join(f"{float(v):.6f}" for v in vec) + "]"


def _rows_to_results(rows, min_score: float) -> list[tuple[float, dict[str, Any]]]:
    out: list[tuple[float, dict[str, Any]]] = []
    for source_id, title, year, url, text, score in rows:
        score = float(score) if score is not None else 0.0
        if score < min_score:
            continue
        out.append(
            (score, {"id": source_id, "title": title, "year": year, "url": url or "", "text": text})
        )
    return out


# How many passages one document may contribute to an answer. The six best
# matches for "¿Puedo construir en una zona inundable en Ponce?" were all from
# Ponce's mitigation plan - a long document with many similar passages - so the
# Reglamento Conjunto, the rule that actually governs it, never reached the
# answer. More candidates are fetched, then each document is capped.
PER_DOCUMENT = 2
CANDIDATES_PER_RESULT = 5


def _spread(
    results: list[tuple[float, dict[str, Any]]], top_k: int
) -> list[tuple[float, dict[str, Any]]]:
    """The best passages, at most PER_DOCUMENT from any one document, in score order."""
    taken: dict[str, int] = {}
    out = []
    for score, doc in results:
        key = doc["id"]
        if taken.get(key, 0) >= PER_DOCUMENT:
            continue
        taken[key] = taken.get(key, 0) + 1
        out.append((score, doc))
        if len(out) == top_k:
            break
    return out


def retrieve_cloud(
    query: str, top_k: int = 5, min_score: float = 0.15, jurisdiction: str | None = None
) -> list[tuple[float, dict[str, Any]]]:
    """Semantic search over document_chunks in Cloud SQL (pgvector cosine).

    If `jurisdiction` (a municipio) is given, results are scoped to that municipio's
    documents plus island-wide ("Puerto Rico") documents. Falls back to an unscoped
    search if the scoped one finds nothing, so it always answers.
    """
    from . import db

    qvec = _get_query_model().encode([query], normalize_embeddings=True, show_progress_bar=False)[0]
    lit = _vector_literal(qvec)
    base = (
        "SELECT d.source_id, d.title, d.year, d.url, c.text, "
        "1 - (c.embedding <=> %s::vector) AS score "
        "FROM document_chunks c JOIN documents d ON c.document_id = d.id "
    )
    tail = "ORDER BY c.embedding <=> %s::vector LIMIT %s"
    with db.connection() as conn:
        cur = conn.cursor()
        rows = []
        if jurisdiction:
            # An HNSW index finds the nearest chunks in the whole corpus and only
            # then applies the WHERE, so a municipality filter threw away nearly
            # all of them: a question about Loíza came back with one chunk, and
            # the answer read as though the corpus had nothing on Loíza. Iterative
            # scan keeps searching until the filter is satisfied.
            cur.execute("SET LOCAL hnsw.iterative_scan = relaxed_order")
            # Island-wide documents apply everywhere, and their inventory marks
            # them "N/A" or leaves the municipality blank - not "Puerto Rico",
            # which is all this used to accept. So every question that named a
            # place left out the Reglamento Conjunto and the island-wide laws:
            # "can I build in a flood zone in Ponce?" never read the permitting
            # rules. Found on 6 Oct 2026; no document was labelled "Puerto Rico".
            cur.execute(
                base
                + "WHERE d.jurisdiction ILIKE %s OR d.jurisdiction IS NULL "
                + "OR d.jurisdiction IN ('Puerto Rico', 'N/A', '') "
                + tail,
                (lit, jurisdiction, lit, top_k * CANDIDATES_PER_RESULT),
            )
            rows = cur.fetchall()
        if not rows:  # no scope, or scoped search found nothing -> unscoped
            cur.execute(base + tail, (lit, lit, top_k * CANDIDATES_PER_RESULT))
            rows = cur.fetchall()
    return _spread(_rows_to_results(rows, min_score), top_k)


_jurisdictions_cache: list[str] | None = None


def _corpus_jurisdictions() -> list[str]:
    global _jurisdictions_cache
    if _jurisdictions_cache is None:
        import psycopg2

        with psycopg2.connect(settings.database_url) as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT DISTINCT jurisdiction FROM documents WHERE jurisdiction IS NOT NULL"
            )
            _jurisdictions_cache = [r[0] for r in cur.fetchall()]
    return _jurisdictions_cache


def detect_municipio(text: str) -> str | None:
    """Return a municipio jurisdiction mentioned in the text, if the corpus has docs
    for it (accent-insensitive). Island-wide 'Puerto Rico' is not a scope."""
    if not settings.database_url:
        return None
    t = _strip(text)
    for j in _corpus_jurisdictions():
        if j.strip().lower() == "puerto rico":
            continue
        if _strip(j) in t:
            return j
    return None


def _strip(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in text if not unicodedata.combining(c))


def load_documents() -> list[dict[str, Any]]:
    with DATA_PATH.open(encoding="utf-8") as f:
        docs = json.load(f)
    seen = {d["id"] for d in docs}
    for extra in EXTRA_PATHS:
        if extra.exists():
            with extra.open(encoding="utf-8") as f:
                for d in json.load(f):
                    if d["id"] not in seen:
                        docs.append(d)
                        seen.add(d["id"])
    return docs


def _doc_text_for_embedding(doc: dict[str, Any]) -> str:
    parts = [doc.get("title", ""), " ".join(doc.get("tags", [])), doc.get("text", "")]
    return "\n".join(p for p in parts if p)


class SemanticIndex:
    def __init__(self, model_name: str = EMBEDDING_MODEL_NAME):
        self.model = SentenceTransformer(model_name)
        self.documents: list[dict[str, Any]] = []
        self.embeddings: np.ndarray | None = None

    def build(self, documents: list[dict[str, Any]]) -> None:
        self.documents = documents
        texts = [_doc_text_for_embedding(d) for d in documents]
        self.embeddings = self.model.encode(
            texts,
            normalize_embeddings=True,
            show_progress_bar=False,
        )

    def search(
        self, query: str, top_k: int = 3, min_score: float = 0.15
    ) -> list[tuple[float, dict[str, Any]]]:
        if self.embeddings is None or len(self.documents) == 0:
            return []
        q_vec = self.model.encode([query], normalize_embeddings=True, show_progress_bar=False)[0]
        scores = self.embeddings @ q_vec
        order = np.argsort(-scores)
        results: list[tuple[float, dict[str, Any]]] = []
        for idx in order[:top_k]:
            score = float(scores[idx])
            if score < min_score:
                continue
            results.append((score, self.documents[idx]))
        return results


_index: SemanticIndex | None = None


def _get_index() -> SemanticIndex:
    global _index
    if _index is None:
        idx = SemanticIndex()
        idx.build(load_documents())
        _index = idx
    return _index


def retrieve(query: str, top_k: int = 3, jurisdiction: str | None = None) -> list[dict[str, Any]]:
    if settings.database_url:
        return [doc for _, doc in retrieve_cloud(query, top_k=top_k, jurisdiction=jurisdiction)]
    index = _get_index()
    return [doc for _, doc in index.search(query, top_k=top_k)]


def retrieve_with_scores(
    query: str, top_k: int = 3, jurisdiction: str | None = None
) -> list[tuple[float, dict[str, Any]]]:
    if settings.database_url:
        return retrieve_cloud(query, top_k=top_k, jurisdiction=jurisdiction)
    index = _get_index()
    return index.search(query, top_k=top_k)


def compose_answer(query: str, docs: list[dict[str, Any]], layers: list[str]) -> dict[str, Any]:
    if not docs:
        return {
            "answer_es": (
                "No se encontró evidencia suficiente en los documentos disponibles para "
                "responder esta pregunta con confianza. Intente reformular la pregunta o "
                "consulte directamente a la Junta de Planificación o al municipio correspondiente."
            ),
            "citations": [],
            "suggested_layers": layers,
        }

    intro = f"Con base en los documentos disponibles, sobre «{query.strip()}»:"
    bullets = []
    for d in docs:
        snippet = d["text"].strip()
        if len(snippet) > 260:
            snippet = snippet[:257].rstrip() + "…"
        bullets.append(f"• Según {d['title']} ({d['year']}): {snippet}")
    answer = intro + "\n\n" + "\n\n".join(bullets)

    citations = [
        {
            "id": d["id"],
            "title": display_title(d["title"]),
            "year": d["year"],
            "doc_id": citation_id(d["id"]),
        }
        for d in docs
    ]
    return {
        "answer_es": answer,
        "citations": citations,
        "suggested_layers": layers,
    }
