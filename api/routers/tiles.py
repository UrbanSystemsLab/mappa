"""Map tiles, and the whole-layer GeoJSON that predates them."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, Response

from .. import spatial
from .. import tiles as tile_service

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


@router.get("/tiles/{name}.json")
def tilejson(name: str, request: Request) -> JSONResponse:
    doc = tile_service.tilejson(name, str(request.base_url).rstrip("/"))
    if doc is None:
        raise HTTPException(status_code=404, detail=f"unknown layer: {name}")
    return JSONResponse(doc, headers={"Cache-Control": "public, max-age=3600"})


@router.get("/layer/{name}")
def layer_geojson(name: str) -> JSONResponse:
    """A whole layer as GeoJSON.

    Superseded by tiles for anything large - this caps features, which is how
    the west half of the island once went missing - but kept for small layers
    and for callers that want the data rather than a picture.
    """
    data = spatial.layer_geojson(name)
    if data is None:
        raise HTTPException(status_code=404, detail=f"unknown layer: {name}")
    return JSONResponse(data, headers={"Cache-Control": "public, max-age=86400"})
