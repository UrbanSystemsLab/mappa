import json
import os
import unicodedata
from pathlib import Path
from typing import Any

import numpy as np
from sentence_transformers import SentenceTransformer

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATA_PATH = DATA_DIR / "documents.json"
# Extra local corpora merged in if present (e.g. documents pulled from Drive).
EXTRA_PATHS = [DATA_DIR / "planning_docs.json", DATA_DIR / "drive_docs.json"]

EMBEDDING_MODEL_NAME = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

# When DATABASE_URL is set, retrieval runs against Cloud SQL (pgvector) over the full
# corpus; otherwise it falls back to the in-memory index over the local JSON corpus.
DB_URL = os.environ.get("DATABASE_URL")
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
        out.append((score, {"id": source_id, "title": title, "year": year, "url": url or "", "text": text}))
    return out


def retrieve_cloud(
    query: str, top_k: int = 5, min_score: float = 0.15, jurisdiction: str | None = None
) -> list[tuple[float, dict[str, Any]]]:
    """Semantic search over document_chunks in Cloud SQL (pgvector cosine).

    If `jurisdiction` (a municipio) is given, results are scoped to that municipio's
    documents plus island-wide ("Puerto Rico") documents. Falls back to an unscoped
    search if the scoped one finds nothing, so it always answers.
    """
    import psycopg2

    qvec = _get_query_model().encode([query], normalize_embeddings=True, show_progress_bar=False)[0]
    lit = _vector_literal(qvec)
    base = (
        "SELECT d.source_id, d.title, d.year, d.url, c.text, "
        "1 - (c.embedding <=> %s::vector) AS score "
        "FROM document_chunks c JOIN documents d ON c.document_id = d.id "
    )
    tail = "ORDER BY c.embedding <=> %s::vector LIMIT %s"
    with psycopg2.connect(DB_URL) as conn, conn.cursor() as cur:
        rows = []
        if jurisdiction:
            cur.execute(
                base + "WHERE d.jurisdiction ILIKE %s OR d.jurisdiction ILIKE 'Puerto Rico' " + tail,
                (lit, jurisdiction, lit, top_k),
            )
            rows = cur.fetchall()
        if not rows:  # no scope, or scoped search found nothing -> unscoped
            cur.execute(base + tail, (lit, lit, top_k))
            rows = cur.fetchall()
    return _rows_to_results(rows, min_score)


_jurisdictions_cache: list[str] | None = None


def _corpus_jurisdictions() -> list[str]:
    global _jurisdictions_cache
    if _jurisdictions_cache is None:
        import psycopg2

        with psycopg2.connect(DB_URL) as conn, conn.cursor() as cur:
            cur.execute("SELECT DISTINCT jurisdiction FROM documents WHERE jurisdiction IS NOT NULL")
            _jurisdictions_cache = [r[0] for r in cur.fetchall()]
    return _jurisdictions_cache


def detect_municipio(text: str) -> str | None:
    """Return a municipio jurisdiction mentioned in the text, if the corpus has docs
    for it (accent-insensitive). Island-wide 'Puerto Rico' is not a scope."""
    if not DB_URL:
        return None
    t = _strip(text)
    for j in _corpus_jurisdictions():
        if j.strip().lower() == "puerto rico":
            continue
        if _strip(j) in t:
            return j
    return None

LAYER_KEYWORDS: dict[str, list[str]] = {
    "inundacion": ["inundacion", "inundable", "flood", "firm", "fema", "rio", "marejada"],
    "deslizamiento": ["deslizamiento", "ladera", "derrumbe", "landslide", "pendiente"],
    "zonificacion": ["zonificacion", "zona", "distrito", "calificacion", "uso", "permiso", "construccion"],
    "costa": ["costa", "costanera", "playa", "zmt", "maritimo", "manglar"],
    "humedal": ["humedal", "pantano", "cienaga", "wetland"],
}


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

    def search(self, query: str, top_k: int = 3, min_score: float = 0.15) -> list[tuple[float, dict[str, Any]]]:
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
    if DB_URL:
        return [doc for _, doc in retrieve_cloud(query, top_k=top_k, jurisdiction=jurisdiction)]
    index = _get_index()
    return [doc for _, doc in index.search(query, top_k=top_k)]


def retrieve_with_scores(
    query: str, top_k: int = 3, jurisdiction: str | None = None
) -> list[tuple[float, dict[str, Any]]]:
    if DB_URL:
        return retrieve_cloud(query, top_k=top_k, jurisdiction=jurisdiction)
    index = _get_index()
    return index.search(query, top_k=top_k)


def infer_layers(query: str) -> list[str]:
    q = _strip(query)
    return [layer for layer, words in LAYER_KEYWORDS.items() if any(w in q for w in words)]


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
            "confidence": "baja",
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
        {"id": d["id"], "title": d["title"], "year": d["year"], "url": d.get("url", "")}
        for d in docs
    ]
    confidence = "alta" if len(docs) >= 2 else "media"
    return {
        "answer_es": answer,
        "citations": citations,
        "suggested_layers": layers,
        "confidence": confidence,
    }
