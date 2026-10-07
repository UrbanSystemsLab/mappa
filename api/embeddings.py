"""The text-embedding model, shared by document search and layer search."""

from __future__ import annotations

from sentence_transformers import SentenceTransformer

from core import EMBEDDING_MODEL

from .cache import cached


@cached()
def encoder() -> SentenceTransformer:
    return SentenceTransformer(EMBEDDING_MODEL)


def vector(text: str) -> str:
    """The text as a pgvector literal, normalised so cosine distance applies."""
    v = encoder().encode([text], normalize_embeddings=True, show_progress_bar=False)[0]
    return "[" + ",".join(f"{float(x):.6f}" for x in v) + "]"
