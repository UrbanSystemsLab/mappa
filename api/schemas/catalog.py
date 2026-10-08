"""The layer catalogue as the API returns it."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

LayerStatus = Literal["published", "loaded", "catalogued", "duplicate", "draft", "hidden"]


class LayerSource(BaseModel):
    agency: str | None = None
    inventory: str | None = Field(
        None, description="Which La Maraña inventory the layer comes from."
    )
    url: str | None = None
    year: int | None = None
    license: str | None = None
    metadata_status: Literal["confirmed", "inferred", "reconstructed", "unknown"] | None = Field(
        None,
        description="La Maraña's own rating of the layer's metadata. Null unless they gave one.",
    )


class Layer(BaseModel):
    id: str = Field(description="Stable identifier. Use it to fetch one layer or to turn it on.")
    name: str = Field(description="In the language asked for; Spanish when no English name exists.")
    description: str | None = None
    category: str
    category_source: str | None = Field(
        None, description="The category exactly as their inventory writes it."
    )
    subcategory: str | None = None
    theme: str | None = None
    keywords: list[str] = []
    source: LayerSource
    geometry_type: str | None = Field(None, description="POINT, MULTIPOLYGON, MULTILINESTRING...")
    feature_count: int | None = None
    srid: int | None = None
    min_zoom: int | None = None
    max_zoom: int | None = None
    label_column: str | None = None
    sublabel_column: str | None = None
    style: dict[str, Any] = Field({}, description="Display hints; at least `color`.")
    property_labels: dict[str, Any] = Field(
        {}, description="Readable names for property keys, per language."
    )
    value_labels: dict[str, Any] = {}
    dataset_version: int | None = None
    status: LayerStatus
    featured: bool = Field(False, description="On La Maraña's prioritization matrix.")
    featured_note: str | None = None
    reliability: Literal["reliable", "needs_review", "outdated"] | None = None
    tile_properties_order: list[str] = Field(
        [], description="The feature properties carried in this layer's tiles, in display order."
    )
    available: bool = Field(description="True if the layer can be drawn: its tiles exist.")
    queryable: bool = Field(description="True if the assistant can answer from it.")
    tiles_url: str | None = Field(
        None,
        description="Vector tile URL template, relative to the API's origin: "
        "/api/v1/tiles/{table}/{z}/{x}/{y}.mvt?v=N. Null when there is no data to draw.",
    )


class LayerList(BaseModel):
    total: int
    limit: int
    offset: int
    layers: list[Layer]


class Category(BaseModel):
    category: str
    available: int = Field(description="Layers in this category that can be drawn.")
    count: int = Field(description="All layers in this category.")
