"""Places: finding one by name, and what the data says at a clicked point."""

from __future__ import annotations

from fastapi import APIRouter, Response

from .. import spatial
from ..schemas import Location, PlaceMatch

router = APIRouter(tags=["places"])


@router.get("/places", response_model=list[PlaceMatch])
def search(q: str, response: Response, limit: int = 8) -> list:
    """Municipios, barrios and comunidades by name, accent- and case-insensitive."""
    response.headers["Cache-Control"] = "public, max-age=600"
    return spatial.search_places(q, min(limit, 20))


@router.get("/locate", response_model=Location)
def locate(lng: float, lat: float) -> dict:
    """What the click-checked layers say about one point."""
    return spatial.locate(lng, lat)
