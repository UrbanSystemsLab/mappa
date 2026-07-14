import json
import unicodedata
from pathlib import Path
from typing import Any

import numpy as np
from sentence_transformers import SentenceTransformer

DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "documents.json"

EMBEDDING_MODEL_NAME = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

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
        return json.load(f)


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


def retrieve(query: str, top_k: int = 3) -> list[dict[str, Any]]:
    index = _get_index()
    return [doc for _, doc in index.search(query, top_k=top_k)]


def retrieve_with_scores(query: str, top_k: int = 3) -> list[tuple[float, dict[str, Any]]]:
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
