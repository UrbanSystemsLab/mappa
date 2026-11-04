"""Measurements on map layers, scoped to a place when one is given.

Every figure the assistant states comes from one of these: computed from the
shapes in the database, never read out of a document. Layers arrive as registry
rows, so the table names interpolated below come from the catalogue, not from
a request.

Each runs under the connection's statement timeout (settings.db_statement_timeout_ms).
A measurement takes about a second; one that runs out the timeout is reported to
the assistant as too slow, so it cannot hold a connection the map needs.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import psycopg2

from .. import db
from .layers import Layer, roles
from .places import Place, municipio_at, scope

log = logging.getLogger("mappa.spatial")

_POINT = "ST_SetSRID(ST_MakePoint(%s, %s), 4326)"
_METRES_PER_DEGREE = 111_320.0


def count(layer: Layer, place: Place | None = None) -> int:
    """Features of a layer, island-wide or inside a place."""
    where, params = scope(place)
    with db.connection() as conn:
        cur = conn.cursor()
        cur.execute(
            f'SELECT count(*) FROM "{layer.table}" f WHERE f.geom IS NOT NULL{where}', params
        )
        return cur.fetchone()[0]


def count_inside(layer: Layer, area: Layer, place: Place | None = None) -> tuple[int, int]:
    """How many of a layer's features fall inside another layer's areas, of how many."""
    where, params = scope(place)
    with db.connection() as conn:
        cur = conn.cursor()
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
    Each is first cut to the place's box: a hazard shape can have a million
    points, nearly all far outside the place.
    """
    with db.connection() as conn:
        cur = conn.cursor()
        cur.execute(
            f"""SELECT ST_Area(r.geom::geography) / 1e6,
                       coalesce((SELECT ST_Area(ST_Union(ST_Intersection(
                                    ST_MakeValid(ST_ClipByBox2D(ST_Force2D(a.geom), r.geom::box2d)),
                                    r.geom))::geography) / 1e6
                                 FROM "{area.table}" a
                                 WHERE a.geom IS NOT NULL AND ST_Intersects(a.geom, r.geom)), 0)
                FROM reference_units r WHERE r.unit_code = %s""",
            (place.unit_code,),
        )
        total, covered = cur.fetchone()
    return float(total), float(covered)


KINDS_AREA_MS = 10_000
DOMINANT = 0.9  # a column whose one value holds more of the features than this sorts nothing
# Bumped when how kinds are worked out changes, so stored profiles are measured again.
KINDS_VERSION = 2
MAX_KINDS = 40  # more different values than this and a column names things, not kinds


Kinds = list[tuple[str, int, float | None]]  # (kind, features, km² or None)


def kinds(
    layer: Layer, columns: tuple[str, ...], place: Place | None = None, limit: int = 8
) -> dict[str, Kinds]:
    """What a layer holds in a place, by kind: from the column that sorts its
    features into a few kinds (a land use class, a hazard level), the commonest
    kinds, how many features have each and - for an area layer - the km² each
    covers inside the place. Columns that name each feature are left out.

    The columns come from the registry, never from a request.
    """
    where, params = scope(place)
    columns = tuple(c for c in columns if c != layer.label)[:8]
    if not columns:
        return {}
    with db.connection() as conn:
        cur = conn.cursor()
        # For each column: how many different values, how long they are, and how
        # many features share the commonest, and whether they are all numbers. A
        # column sorts features into kinds when its values are words that repeat,
        # few of them, and no one value holds nearly all (a vertical datum the
        # same on every shape says nothing). Of those, the
        # one with the longest values describes ("Suelo Urbano") rather than codes ("SU").
        per_column = ", ".join(
            f"(SELECT count(DISTINCT v) FROM (SELECT nullif(trim(\"{c}\"::text), '') v FROM s) x), "
            f'(SELECT avg(length("{c}"::text)) FROM s), '
            f'(SELECT max(n) FROM (SELECT count(*) n FROM s GROUP BY "{c}") x), '
            f"(SELECT bool_and(\"{c}\"::text ~ '^[-0-9.,]*$') FROM s)"
            for c in columns
        )
        picked = ", ".join(f'f."{c}"' for c in columns)
        cur.execute(
            f'WITH s AS MATERIALIZED (SELECT {picked} FROM "{layer.table}" f '
            f"WHERE f.geom IS NOT NULL{where} LIMIT 5000) "
            f"SELECT (SELECT count(*) FROM s), {per_column}",
            params,
        )
        rows, *row = cur.fetchone()
        stats = [(c, *row[4 * i : 4 * i + 4]) for i, c in enumerate(columns)]
        # Numbers are measurements or identifiers, not kinds.
        sorting = sorted(
            [
                (c, length or 0)
                for c, n, length, top, numeric in stats
                if 2 <= n <= MAX_KINDS
                and n < rows
                and (top or 0) <= DOMINANT * rows
                and not numeric
            ],
            key=lambda x: -x[1],
        )[:1]
        # Only shapes crossing the place's edge are cut, and first to the
        # place's box: a hazard shape can have a million points, nearly all
        # far outside the place.
        size = (
            "sum(CASE WHEN ST_Within(f.geom, u.geom) THEN ST_Area(f.geom::geography) "
            "ELSE ST_Area(ST_Intersection(ST_MakeValid(ST_ClipByBox2D(ST_Force2D(f.geom), "
            "u.geom::box2d)), u.geom)::geography) END) / 1e6"
            if place is not None and layer.is_area
            else "sum(ST_Area(f.geom::geography)) / 1e6"
            if layer.is_area
            else "NULL"
        )
        unit = (
            ", (SELECT geom FROM reference_units WHERE unit_code = %s) u"
            if place is not None and layer.is_area
            else ""
        )
        out = {}
        for c, _ in sorting:
            query = f"""SELECT nullif(trim(f."{c}"::text), '') AS kind, count(*), {{size}}
                    FROM "{layer.table}" f{{unit}} WHERE f.geom IS NOT NULL{where}
                    GROUP BY 1 ORDER BY {{order}} DESC NULLS LAST LIMIT %s"""
            try:
                # A few huge shapes on the place's edge can take long to cut;
                # then the kinds are counted without their area.
                cur.execute("SAVEPOINT kinds; SET LOCAL statement_timeout = %s", (KINDS_AREA_MS,))
                cur.execute(
                    query.format(size=size, unit=unit, order="3" if layer.is_area else "2"),
                    ([place.unit_code] if unit else []) + params + [limit],
                )
            except (psycopg2.errors.QueryCanceled, psycopg2.errors.InternalError_):
                log.info("kinds of %s: area too slow, counting only", layer.id)
                cur.execute("ROLLBACK TO SAVEPOINT kinds")
                cur.execute(query.format(size="NULL", unit="", order="2"), [*params, limit])
            out[c] = [
                (r[0] or "", int(r[1]), float(r[2]) if r[2] is not None else None)
                for r in cur.fetchall()
            ]
    return out


@dataclass(frozen=True, slots=True)
class Feature:
    """One feature an answer found: what it is called (when the layer may say),
    where it is, and how far, when measured from a point."""

    name: str | None
    lng: float
    lat: float
    metres: float | None = None


def _name(layer: Layer) -> str:
    return f"nullif(trim(f.\"{layer.label}\"::text), '')" if layer.names_shown else "NULL"


def nearest(layer: Layer, lng: float, lat: float, n: int = 3) -> list[Feature]:
    """The n features of a layer closest to a point, with their distance on the
    earth. Uses the spatial index to find candidates, then measures exactly."""
    with db.connection() as conn:
        cur = conn.cursor()
        cur.execute(
            f"""SELECT name, ST_X(p), ST_Y(p), ST_Distance(g::geography, pt::geography)
                FROM (SELECT {_name(layer)} AS name, ST_PointOnSurface(f.geom) AS p,
                             f.geom AS g, {_POINT} AS pt
                      FROM "{layer.table}" f WHERE f.geom IS NOT NULL
                      ORDER BY f.geom <-> {_POINT} LIMIT %s) s
                ORDER BY 4""",
            (lng, lat, lng, lat, n),
        )
        return [Feature(r[0], float(r[1]), float(r[2]), float(r[3])) for r in cur.fetchall()]


def features(
    layer: Layer,
    place: Place | None = None,
    inside: Layer | None = None,
    near: tuple[Layer, int] | None = None,
    around: tuple[float, float, int] | None = None,
    limit: int = 25,
) -> tuple[int, list[Feature]]:
    """A layer's features that meet every condition given, and how many there are.

    inside  inside another layer's areas
    near    within so many metres of another layer
    around  within so many metres of a point (lng, lat, metres)

    The count is of features; the list holds one entry per name when the layer
    names its features (a river is many segments of one name), nearest a point
    first when there is one.
    """
    where, params = scope(place)
    if inside is not None:
        where += (
            f' AND EXISTS (SELECT 1 FROM "{inside.table}" a WHERE ST_Intersects(a.geom, f.geom))'
        )
    if near is not None:
        other, metres = near
        where += (
            f' AND EXISTS (SELECT 1 FROM "{other.table}" o WHERE o.geom && ST_Expand(f.geom, %s) '
            f"AND ST_DWithin(o.geom::geography, f.geom::geography, %s))"
        )
        params += [metres / _METRES_PER_DEGREE, metres]
    order = "1"
    if around is not None:
        lng, lat, metres = around
        where += (
            f" AND f.geom && ST_Expand({_POINT}, %s) "
            f"AND ST_DWithin(f.geom::geography, {_POINT}::geography, %s)"
        )
        params += [lng, lat, metres / _METRES_PER_DEGREE, lng, lat, metres]
    with db.connection() as conn:
        cur = conn.cursor()
        cur.execute(
            f'SELECT count(*) FROM "{layer.table}" f WHERE f.geom IS NOT NULL{where}', params
        )
        total = cur.fetchone()[0]
        distance = "NULL"
        if around is not None:
            distance = f"ST_Distance(f.geom::geography, {_POINT}::geography)"
            order = "4"
        cur.execute(
            f"""SELECT * FROM (
                    SELECT DISTINCT ON (coalesce(name, id::text)) name, x, y, metres FROM (
                        SELECT {_name(layer)} AS name, ST_X(ST_PointOnSurface(f.geom)) AS x,
                               ST_Y(ST_PointOnSurface(f.geom)) AS y, {distance} AS metres,
                               row_number() OVER () AS id
                        FROM "{layer.table}" f WHERE f.geom IS NOT NULL{where}
                        LIMIT 2000) f
                    ORDER BY coalesce(name, id::text), metres) d
                ORDER BY {order} LIMIT %s""",
            ([lng, lat] if around is not None else []) + params + [limit],
        )
        found = [
            Feature(r[0], float(r[1]), float(r[2]), float(r[3]) if r[3] is not None else None)
            for r in cur.fetchall()
        ]
    return total, found


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
