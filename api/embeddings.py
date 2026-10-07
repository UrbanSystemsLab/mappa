"""The text-embedding model, shared by document search and layer search."""

from __future__ import annotations

import threading

from sentence_transformers import SentenceTransformer

from core import EMBEDDING_MODEL

from .cache import cached

# The model is not safe to run from several threads at once: concurrent calls
# crash the process. One encode takes milliseconds, so they take turns.
_lock = threading.Lock()


@cached()
def encoder() -> SentenceTransformer:
    return SentenceTransformer(EMBEDDING_MODEL)


def vector(text: str) -> str:
    """The text as a pgvector literal, normalised so cosine distance applies."""
    model = encoder()
    with _lock:
        v = model.encode([text], normalize_embeddings=True, show_progress_bar=False)[0]
    return "[" + ",".join(f"{float(x):.6f}" for x in v) + "]"
