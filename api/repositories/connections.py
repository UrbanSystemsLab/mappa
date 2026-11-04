"""How layers, documents and places connect.

Two tables join them, both written by pipelines from the data itself:

  layer_documents  which documents discuss each layer (link_layer_documents)
  place_profiles   what each standard layer holds in each place (profile_places)

so an answer about a place can start from what the map holds there and which of
its own documents discuss those layers, instead of finding each separately.
Both tables are optional: before the pipelines have run, everything here
returns nothing and the tools measure and search as before.
"""

from __future__ import annotations

from dataclasses import dataclass

import psycopg2

from .. import db
from .documents import display_title
from .layers import Fields, Layer, fields_from, roles
from .places import Place
from .spatial import Kinds


@dataclass(frozen=True, slots=True)
class Profile:
    layer: Layer
    features: int
    column: str | None
    kinds: Kinds
    fields: Fields | None = None  # the layer's dictionary, in the reader's language


@dataclass(frozen=True, slots=True)
class LinkedDocument:
    id: int
    title: str
    year: int | None
    passages: int  # how many of its passages discuss the layers asked about
    layers: tuple[str, ...]  # the layer ids it discusses
    layer_names: tuple[str, ...] = ()  # the same, named in the reader's language


def _read(sql: str, params: tuple) -> list[tuple]:
    try:
        with db.connection() as conn:
            cur = conn.cursor()
            cur.execute(sql, params)
            return cur.fetchall()
    except psycopg2.errors.UndefinedTable:  # the pipelines have not run here yet
        return []


def stored(layer: Layer, place: Place) -> Profile | None:
    """What profile_places measured for this layer in this place, if it did."""
    rows = _read(
        "SELECT features, column_name, kinds FROM place_profiles "
        "WHERE unit_code = %s AND layer_id = %s",
        (place.unit_code, layer.id),
    )
    if not rows:
        return None
    features, column, kinds = rows[0]
    return Profile(layer, features, column, [(k, int(n), km2) for k, n, km2 in kinds])


def profile(place: Place, lang: str = "en") -> list[Profile]:
    """Every standard layer measured in this place, those with something there first."""
    by_id = {r.layer.id: r.layer for r in roles().values()}
    rows = _read(
        """SELECT p.layer_id, p.features, p.column_name, p.kinds,
                  r.tile_properties, r.property_labels, r.value_labels
           FROM place_profiles p JOIN layer_registry r ON r.id = p.layer_id
           WHERE p.unit_code = %s""",
        (place.unit_code,),
    )
    out = [
        Profile(
            by_id[lid],
            features,
            column,
            [(k, int(n), km2) for k, n, km2 in kinds],
            fields_from(columns, labels, values, lang),
        )
        for lid, features, column, kinds, columns, labels, values in rows
        if lid in by_id
    ]
    return sorted(out, key=lambda p: (p.features == 0, p.layer.id))


def documents(
    place: Place | None = None,
    layer_ids: list[str] | None = None,
    limit: int = 8,
    lang: str = "en",
) -> list[LinkedDocument]:
    """The documents that discuss these layers - or any layer - most first: the
    place's own when there is a place, else all of them."""
    where, params = [], []
    if place is not None and place.municipio:
        where.append("d.jurisdiction ILIKE %s")
        params.append(place.municipio)
    if layer_ids:
        where.append("l.layer_id = ANY(%s)")
        params.append(layer_ids)
    name = "r.name_es" if lang == "es" else "coalesce(r.name_en, r.name_es)"
    # A layer most documents mention (special communities, shelters) says less
    # about any one of them than a layer few mention, so each link counts its
    # passages (dampened: a long plan repeats itself) times how rare the layer is.
    rows = _read(
        f"""WITH spread AS (SELECT layer_id, count(*) AS docs FROM layer_documents GROUP BY 1),
                 total AS (SELECT count(DISTINCT document_id) AS docs FROM layer_documents),
                 links AS (
                   SELECT l.*, ln(1 + l.passages) * ln(1 + total.docs::float / spread.docs) AS weight
                   FROM layer_documents l JOIN spread USING (layer_id), total)
            SELECT d.id, d.title, d.year, sum(l.passages)::int,
                   array_agg(l.layer_id ORDER BY l.weight DESC),
                   array_agg({name} ORDER BY l.weight DESC)
            FROM links l JOIN documents d ON d.id = l.document_id
                 JOIN layer_registry r ON r.id = l.layer_id
            {"WHERE " + " AND ".join(where) if where else ""}
            GROUP BY d.id, d.title, d.year ORDER BY sum(l.weight) DESC LIMIT %s""",
        (*params, limit),
    )
    return [
        LinkedDocument(i, display_title(t), y, n, tuple(ids), tuple(x for x in names if x))
        for i, t, y, n, ids, names in rows
    ]


def document_ids(layer: Layer, place: Place | None = None, limit: int = 12) -> list[int]:
    """The documents that discuss a layer most, the place's own when there is one."""
    return [d.id for d in documents(place, [layer.id], limit)]
