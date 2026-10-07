"""Places: finding one by name, and what the data says at a clicked point."""

from __future__ import annotations

from fastapi import APIRouter, Response

from ..repositories import places, spatial
from ..schemas import Location, PlaceMatch

router = APIRouter(tags=["places"])


@router.get("/places", response_model=list[PlaceMatch])
def search(q: str, response: Response, limit: int = 8) -> list:
    """Municipios, barrios and comunidades by name, accent- and case-insensitive."""
    response.headers["Cache-Control"] = "public, max-age=600"
    return places.search(q, min(limit, 20))


@router.get("/locate", response_model=Location)
def locate(lng: float, lat: float) -> Location:
    """What the click-checked layers say about one point."""
    municipio, checks = spatial.at_point(lng, lat)
    return Location(
        municipio=municipio,
        hazards=[
            {"key": c.key, "name_es": c.name_es, "name_en": c.name_en, "inside": c.inside}
            for c in checks
        ],
    )
