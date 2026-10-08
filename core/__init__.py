"""What the API, the pipelines and the scripts share: settings and fixed facts."""

from .constants import (
    EMBED_DIM,
    EMBEDDING_MODEL,
    MIN_RELEVANCE,
    NOT_LAYER_TABLES,
    TILE_MAX_ZOOM,
    TILE_MIN_ZOOM,
)
from .settings import Settings, settings

__all__ = [
    "EMBEDDING_MODEL",
    "EMBED_DIM",
    "MIN_RELEVANCE",
    "NOT_LAYER_TABLES",
    "TILE_MAX_ZOOM",
    "TILE_MIN_ZOOM",
    "Settings",
    "settings",
]
