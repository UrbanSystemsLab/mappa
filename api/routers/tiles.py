"""Map tiles: Mapbox Vector Tiles, and a TileJSON descriptor per layer.

Both are standard formats, so MapLibre GL, Mapbox GL, OpenLayers or deck.gl can
draw these layers without anything specific to this app.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

from .. import tiles as tile_service
from ..schemas import TileJSON

router = APIRouter(tags=["tiles"])


@router.get("/tiles/{name}/{z}/{x}/{y}.mvt")
def tile(name: str, z: int, x: int, y: int) -> Response:
    """One vector tile, built from PostGIS on demand."""
    try:
        data = tile_service.tile(name, z, x, y)
    except Exception as exc:
        # An empty tile renders as "no features here", which on a hazard layer
        # is indistinguishable from "no hazard here". A 503 makes the client
        # retry and keeps missing data visible rather than silent.
        raise HTTPException(status_code=503, detail=f"tile temporarily unavailable: {exc}") from exc
    if data is None:
        raise HTTPException(status_code=404, detail=f"unknown layer: {name}")
    return Response(
        content=data,
        media_type="application/vnd.mapbox-vector-tile",
        # Versioned in the URL, so a republished layer gets fresh tile URLs and
        # a long cache never serves stale geometry.
        headers={"Cache-Control": "public, max-age=86400, immutable"},
    )


@router.get("/tiles/{name}.json", response_model=TileJSON)
def tilejson(name: str, request: Request, response: Response) -> dict:
    """The layer as a vector source - pass this URL straight to a map library."""
    doc = tile_service.tilejson(name, str(request.base_url).rstrip("/"))
    if doc is None:
        raise HTTPException(status_code=404, detail=f"unknown layer: {name}")
    response.headers["Cache-Control"] = "public, max-age=3600"
    return doc
