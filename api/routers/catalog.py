"""The layer catalogue: what exists, and what the map may draw."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response

from .. import catalog as catalog_service
from ..schemas import Category, Layer, LayerList

router = APIRouter(prefix="/catalog", tags=["catalog"])

# The catalogue changes when data is released, not between requests.
CACHE = "public, max-age=300"


@router.get("/layers", response_model=LayerList)
def layers(
    response: Response,
    lang: str = "es",
    q: str | None = None,
    category: str | None = None,
    available_only: bool = False,
    limit: int = 100,
    offset: int = 0,
) -> dict:
    """Search the catalogue. `available_only` returns only layers that can be drawn."""
    response.headers["Cache-Control"] = CACHE
    return catalog_service.list_layers(
        lang=lang,
        q=q,
        category=category,
        available_only=available_only,
        limit=max(1, min(limit, 1000)),
        offset=offset,
    )


@router.get("/categories", response_model=list[Category])
def categories(response: Response, lang: str = "es", available_only: bool = False) -> list:
    """Categories, with how many layers each holds and how many can be drawn."""
    response.headers["Cache-Control"] = CACHE
    return catalog_service.categories(lang, available_only=available_only)


@router.get("/layers/{layer_id}", response_model=Layer)
def layer(layer_id: str, response: Response, lang: str = "es") -> dict:
    row = catalog_service.get_layer(layer_id, lang)
    if row is None:
        raise HTTPException(status_code=404, detail=f"unknown layer: {layer_id}")
    response.headers["Cache-Control"] = CACHE
    return row
