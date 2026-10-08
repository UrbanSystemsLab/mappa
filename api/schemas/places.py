"""Places, map clicks and tile descriptors as the API returns them."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

BBox = list[float]  # [west, south, east, north], WGS84


class PlaceMatch(BaseModel):
    name: str
    type: Literal["municipio", "barrio", "comunidad"]
    parent: str | None = Field(None, description="The municipio a barrio or comunidad is in.")
    label: str = Field(description='What to show: "Santurce, San Juan".')
    bbox: BBox


class PointCheck(BaseModel):
    key: str = Field(description="The layer role checked, e.g. 'flood'.")
    name_es: str
    name_en: str
    inside: bool = Field(description="Whether the clicked point falls inside that layer.")


class Location(BaseModel):
    """What the data says about one clicked point. Facts about that point only."""

    municipio: str | None
    hazards: list[PointCheck]


class TileJSON(BaseModel):
    """A TileJSON 3.0 descriptor - accepted directly by MapLibre GL and Mapbox GL."""

    tilejson: str = "3.0.0"
    name: str
    tiles: list[str]
    minzoom: int
    maxzoom: int
    bounds: BBox
    vector_layers: list[dict[str, Any]]
