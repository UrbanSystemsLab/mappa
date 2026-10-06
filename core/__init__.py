"""Values that more than one part of the system has to agree on.

Nothing here is a general-purpose dumping ground for constants. A threshold used
in one place belongs next to the code it tunes, where a reader can see what it
does. What belongs here is narrower and more dangerous: a value where `api` and
`pipelines` have to say the same thing, and where disagreeing is silent.

Each one below had already been declared two or three times by the time this was
written, and one pair had already drifted.
"""

from .config import (
    APP_ENV,
    DATABASE_URL,
    EMBED_DIM,
    EMBEDDING_MODEL,
    MIN_RELEVANCE,
    TILE_MAX_ZOOM,
    TILE_MIN_ZOOM,
)

__all__ = [
    "APP_ENV",
    "DATABASE_URL",
    "EMBEDDING_MODEL",
    "EMBED_DIM",
    "MIN_RELEVANCE",
    "TILE_MAX_ZOOM",
    "TILE_MIN_ZOOM",
]
