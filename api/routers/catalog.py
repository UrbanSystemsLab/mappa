"""The layer catalogue: what exists, and what the map may draw."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from .. import catalog as catalog_service

router = APIRouter(prefix="/catalog", tags=["catalog"])

# The catalogue changes when a pipeline runs, not between requests.
CACHE = {"Cache-Control": "public, max-age=300"}


@router.get("/layers")
def layers(
    lang: str = "es",
    q: str | None = None,
    category: str | None = None,
    available_only: bool = False,
    limit: int = 100,
    offset: int = 0,
) -> JSONResponse:
    """Search the catalogue.

    `available_only` is what the map panel asks for - layers it can actually
    draw. Without it the listing also returns layers whose data is loaded but
    which are not offered as toggles, and those still on La Maraña's inventory
    with no data at all, each marked so the UI can say which is which.
    """
    # Their inventory is 649 layers and the panel groups them collapsed by
    # category, so the whole catalogue is one small request rather than paging.
    limit = max(1, min(limit, 1000))
    return JSONResponse(
        catalog_service.list_layers(
            lang=lang,
            q=q,
            category=category,
            available_only=available_only,
            limit=limit,
            offset=offset,
        ),
        headers=CACHE,
    )


@router.get("/categories")
def categories(lang: str = "es", available_only: bool = False) -> JSONResponse:
    """Category facets, counted as live-against-held so the gap is visible."""
    return JSONResponse(
        catalog_service.categories(lang, available_only=available_only), headers=CACHE
    )


@router.get("/layers/{layer_id}")
def layer(layer_id: str, lang: str = "es") -> JSONResponse:
    row = catalog_service.get_layer(layer_id, lang)
    if row is None:
        raise HTTPException(status_code=404, detail=f"unknown layer: {layer_id}")
    return JSONResponse(row, headers=CACHE)
