"""Places: finding one by name, and asking what is true at a point."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from .. import spatial

router = APIRouter(tags=["places"])


@router.get("/places")
def search(q: str, limit: int = 8) -> JSONResponse:
    """Municipios and barrios by name.

    Accent- and case-insensitive, because a resident typing "anasco" should
    find Añasco.
    """
    return JSONResponse(
        spatial.search_places(q, min(limit, 20)), headers={"Cache-Control": "public, max-age=600"}
    )


@router.get("/locate")
def locate(lng: float, lat: float) -> dict:
    """What the loaded layers say about one point - what a map click asks."""
    return spatial.locate(lng, lat)


@router.get("/layers")
def legacy_layers() -> JSONResponse:
    """The original ten-layer list. Superseded by /catalog/layers."""
    return JSONResponse(spatial.list_layers(), headers={"Cache-Control": "public, max-age=3600"})
