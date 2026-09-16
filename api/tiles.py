"""Vector tile service — serve spatial layers as Mapbox Vector Tiles from PostGIS.

Replaces whole-layer GeoJSON. Instead of sending an entire layer to the browser,
the client requests only the tiles covering its viewport at the current zoom, and
PostGIS generates each tile with ST_AsMVT.

Two consequences that matter:

  * No feature cap. Whole-layer GeoJSON forced a _MAX_FEATURES limit (features past
    the cap were silently dropped). Tiles carry every feature; geometry is
    *generalized* per zoom instead — detail the screen cannot resolve is dropped,
    never the feature itself.
  * Payload scales with the view, not the dataset. An island-wide view of a layer
    is a handful of small tiles regardless of how many features the layer holds.

Tiles are immutable for a given (layer, dataset_version, z, x, y), so they are safe
to cache indefinitely at a CDN.
"""

from __future__ import annotations

import logging
import math
import os
import threading
from typing import Any

from . import db

DB_URL = os.environ.get("DATABASE_URL")

log = logging.getLogger(__name__)

# Short on purpose: a slow tile should give up quickly and return empty rather than
# hold a pooled connection while the map waits on it.
TILE_TIMEOUT_MS = int(os.environ.get("TILE_TIMEOUT_MS", "8000"))

# A single map view requests many tiles at once. Without a gate they all try to
# borrow a connection at the same moment and drain the pool, which then fails
# unrelated requests including /ask. Cap in-flight tile queries below the pool size
# so there is always a connection left for everything else.
_TILE_GATE = threading.Semaphore(int(os.environ.get("TILE_CONCURRENCY", "3")))


def tile_bounds_4326(z: int, x: int, y: int) -> tuple[float, float, float, float]:
    """Lon/lat bounds of a Web Mercator tile, computed here rather than in SQL.

    This matters for performance: ST_Transform is STABLE, not IMMUTABLE, so a
    WHERE clause like `geom && ST_Transform(ST_TileEnvelope(z,x,y), 4326)` is not
    folded into a constant — the planner cannot use the GiST index and falls back
    to a full scan, reprojecting every row. Passing plain numbers into
    ST_MakeEnvelope keeps the bbox test index-backed.
    """
    n = 2.0 ** z
    lon1 = x / n * 360.0 - 180.0
    lon2 = (x + 1) / n * 360.0 - 180.0
    lat1 = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))
    lat2 = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (y + 1) / n))))
    return lon1, min(lat1, lat2), lon2, max(lat1, lat2)

# MVT extent in tile-local units. 4096 is the de-facto standard (Mapbox/MapLibre).
_EXTENT = 4096
# Buffer in tile units, so shapes crossing a tile edge render without seams.
_BUFFER = 64
# Max zoom we serve; beyond this the client over-zooms the z14 tile (standard practice).
MAX_ZOOM = 14

# Property columns to carry into the tile, per layer. Kept small on purpose —
# every property is repeated per feature per tile, so this is the main size lever.
_TILE_PROPS = {
    "layer_hospitales": ("nombre", "muni"),
    "layer_refugios_2023": ("instalacio", "municipio"),
    "layer_dotacional_educacion_escuelas_2021": ("escuela", "municipio"),
    "layer_g03_legales_municipios_2015": ("municipio", None),
}


_LAYER_META: dict[str, dict[str, Any]] = {}


def layer_meta(name: str) -> dict[str, Any] | None:
    """Look up a layer in the catalog. Doubles as the whitelist check before the
    layer name is interpolated into SQL."""
    if name in _LAYER_META:
        return _LAYER_META[name]
    with db.connection() as conn:
        cur = conn.cursor()
        
        cur.execute(
            "SELECT layer_name, geometry_type, feature_count FROM spatial_layers WHERE layer_name = %s",
            (name,),
        )
        row = cur.fetchone()
    if row is None:
        return None
    meta = {"layer_name": row[0], "geometry_type": row[1], "feature_count": row[2]}
    _LAYER_META[name] = meta
    return meta


def tile(name: str, z: int, x: int, y: int) -> bytes | None:
    """Return one MVT tile for `name`, or None if the layer is unknown.

    Returns empty bytes when the tile covers no features — a valid, cacheable
    "nothing here" response.
    """
    meta = layer_meta(name)
    if meta is None:
        return None
    if not (0 <= z <= 22) or not (0 <= x < 2 ** z) or not (0 <= y < 2 ** z):
        return None

    from . import catalog
    name_col, sub_col = catalog.tile_columns(name)
    cols = ["id"]
    if name_col:
        cols.append(f'l.{name_col} AS "name"')
    if sub_col:
        cols.append(f'l.{sub_col} AS "sub"')
    select_extra = ", " + ", ".join(cols[1:]) if len(cols) > 1 else ""

    w, s, e, n = tile_bounds_4326(z, x, y)

    # Drop features too small to see at this zoom — sub-pixel shapes cost bytes and
    # render nothing. Area compared in degrees² against the tile's own area, so no
    # per-row reprojection is needed.
    area_filter = ""
    tile_area = max((e - w) * (n - s), 1e-12)
    if "Polygon" in (meta["geometry_type"] or "") and z < 11:
        area_filter = f" AND ST_Area(l.geom) > {tile_area / 4_000_000.0:.12g}"

    # `name` is whitelisted via spatial_layers above; bounds are bound parameters.
    sql = f"""
        SELECT ST_AsMVT(t, 'layer', {_EXTENT}, 'geom') FROM (
            SELECT
                ST_AsMVTGeom(
                    ST_Transform(l.geom, 3857),
                    ST_TileEnvelope(%(z)s, %(x)s, %(y)s), {_EXTENT}, {_BUFFER}, true
                ) AS geom
                {select_extra}
            FROM "{name}" AS l
            WHERE l.geom IS NOT NULL
              AND l.geom && ST_MakeEnvelope(%(w)s, %(s)s, %(e)s, %(n)s, 4326)
              {area_filter}
        ) AS t WHERE t.geom IS NOT NULL
    """
    try:
        with _TILE_GATE, db.connection() as conn:
            cur = conn.cursor()
            cur.execute(f"SET LOCAL statement_timeout = '{TILE_TIMEOUT_MS}ms'")
            cur.execute(sql, {"z": z, "x": x, "y": y, "w": w, "s": s, "e": e, "n": n})
            row = cur.fetchone()
        return bytes(row[0]) if row and row[0] else b""
    except Exception as exc:
        log.warning("tile %s %s/%s/%s failed: %s", name, z, x, y, exc)
        return b""


def tilejson(name: str, base_url: str) -> dict[str, Any] | None:
    """TileJSON descriptor so MapLibre can add the layer as a vector source."""
    meta = layer_meta(name)
    if meta is None:
        return None
    return {
        "tilejson": "3.0.0",
        "name": name,
        "tiles": [f"{base_url}/tiles/{name}/{{z}}/{{x}}/{{y}}.mvt"],
        "minzoom": 0,
        "maxzoom": MAX_ZOOM,
        "bounds": [-67.3, 17.85, -65.2, 18.55],  # Puerto Rico
        "vector_layers": [{"id": "layer", "fields": {}}],
    }
