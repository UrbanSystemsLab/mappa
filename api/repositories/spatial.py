"""Measurements on map layers, scoped to a place when one is given.

Every figure the assistant states comes from one of these: computed from the
shapes in the database, never read out of a document. Layers arrive as registry
rows, so the table names interpolated below come from the catalogue, not from
a request.
"""

from __future__ import annotations

from dataclasses import dataclass

from .. import db
from .layers import Layer, roles
from .places import Place, municipio_at, scope

_POINT = "ST_SetSRID(ST_MakePoint(%s, %s), 4326)"
_METRES_PER_DEGREE = 111_320.0


def count(layer: Layer, place: Place | None = None) -> int:
    """Features of a layer, island-wide or inside a place."""
    where, params = scope(place)
    with db.connection() as conn:
        cur = conn.cursor()
        cur.execute("SET LOCAL statement_timeout = '45s'")
        cur.execute(
            f'SELECT count(*) FROM "{layer.table}" f WHERE f.geom IS NOT NULL{where}', params
        )
        return cur.fetchone()[0]


def count_inside(layer: Layer, area: Layer, place: Place | None = None) -> tuple[int, int]:
    """How many of a layer's features fall inside another layer's areas, of how many."""
    where, params = scope(place)
    with db.connection() as conn:
        cur = conn.cursor()
        cur.execute("SET LOCAL statement_timeout = '90s'")
        cur.execute(
            f'SELECT count(*) FILTER (WHERE EXISTS (SELECT 1 FROM "{area.table}" a '
            f"WHERE ST_Intersects(a.geom, f.geom))), count(*) "
            f'FROM "{layer.table}" f WHERE f.geom IS NOT NULL{where}',
            params,
        )
        inside, total = cur.fetchone()
    return inside, total


def count_within(
    layer: Layer, other: Layer, metres: int, place: Place | None = None
) -> tuple[int, int]:
    """How many of a layer's features lie within `metres` of another layer, of how many.

    Distance is measured on the earth (geography), not in degrees; the bounding
    box test first keeps it fast.
    """
    where, params = scope(place)
    deg = metres / _METRES_PER_DEGREE
    with db.connection() as conn:
        cur = conn.cursor()
        cur.execute("SET LOCAL statement_timeout = '120s'")
        cur.execute(
            f'SELECT count(*) FILTER (WHERE EXISTS (SELECT 1 FROM "{other.table}" o '
            f"WHERE o.geom && ST_Expand(f.geom, %s) "
            f"AND ST_DWithin(o.geom::geography, f.geom::geography, %s))), count(*) "
            f'FROM "{layer.table}" f WHERE f.geom IS NOT NULL{where}',
            [deg, metres, *params],
        )
        near, total = cur.fetchone()
    return near, total


def area_share(area: Layer, place: Place) -> tuple[float, float]:
    """The place's area and how much of it the layer covers, both in km².

    Overlapping shapes are merged before measuring, so nothing is counted twice.
    """
    with db.connection() as conn:
        cur = conn.cursor()
        cur.execute("SET LOCAL statement_timeout = '180s'")
        cur.execute(
            f"""SELECT ST_Area(r.geom::geography) / 1e6,
                       coalesce((SELECT ST_Area(ST_Union(ST_Intersection(
                                    ST_MakeValid(ST_Force2D(a.geom)), r.geom))::geography) / 1e6
                                 FROM "{area.table}" a
                                 WHERE a.geom IS NOT NULL AND ST_Intersects(a.geom, r.geom)), 0)
                FROM reference_units r WHERE r.unit_code = %s""",
            (place.unit_code,),
        )
        total, covered = cur.fetchone()
    return float(total), float(covered)


@dataclass(frozen=True, slots=True)
class PointCheck:
    key: str
    name_es: str
    name_en: str
    inside: bool


def at_point(lng: float, lat: float) -> tuple[str | None, list[PointCheck]]:
    """The municipio a point is in, and whether it falls inside each layer the
    roles mark for checking on a map click."""
    checks = []
    with db.connection() as conn:
        cur = conn.cursor()
        for role in roles().values():
            if not role.checked_on_click:
                continue
            cur.execute(
                f'SELECT EXISTS (SELECT 1 FROM "{role.layer.table}" WHERE ST_Intersects(geom, {_POINT}))',
                (lng, lat),
            )
            checks.append(
                PointCheck(role.name, role.layer.name_es, role.layer.name_en, cur.fetchone()[0])
            )
    return municipio_at(lng, lat), checks
