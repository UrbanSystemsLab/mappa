"""Serve the PostGIS spatial layers to the frontend map as GeoJSON.

Reads from the layer_* tables loaded into Cloud SQL. Layer names are whitelisted
against the spatial_layers catalog before being interpolated into SQL, so there's
no injection surface. Polygon/line geometry is simplified and feature counts are
capped to keep payloads browser-friendly.
"""

from __future__ import annotations

import os
from typing import Any

DB_URL = os.environ.get("DATABASE_URL")

# Simplification tolerance in degrees (~0.0005 ≈ 55 m) by geometry type; points unchanged.
_SIMPLIFY = {"MultiPolygon": 0.0005, "MultiLineString": 0.0003}
_MAX_FEATURES = 6000


def _conn():
    import psycopg2

    return psycopg2.connect(DB_URL)


def list_layers() -> list[dict[str, Any]]:
    """Catalog of loaded layers, for the toggle UI."""
    sql = (
        "SELECT layer_name, theme, year, geometry_type, feature_count, description "
        "FROM spatial_layers ORDER BY theme, layer_name"
    )
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(sql)
        return [
            {
                "layer_name": r[0],
                "theme": r[1],
                "year": r[2],
                "geometry_type": r[3],
                "feature_count": r[4],
                "description": r[5],
            }
            for r in cur.fetchall()
        ]


def locate(lng: float, lat: float) -> dict[str, Any]:
    """Point-in-polygon lookup: which municipio a point falls in, and whether it
    intersects the key hazard layers. Powers the click-on-map interaction."""
    hazard_layers = {
        "flood_2009": "layer_g23_riesgo_inundacion_fema_firms_2009",
        "flood_0_2pct_2018": "layer_g23_riesgo_inundacion_floodzone_0_2pct_seamless_2018",
        "landslide": "layer_landsl_monroe_plus_slop50pct",
    }
    pt = "ST_SetSRID(ST_MakePoint(%s, %s), 4326)"
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"SELECT name FROM reference_units WHERE unit_type='municipio' "
            f"AND ST_Intersects(geom, {pt}) LIMIT 1",
            (lng, lat),
        )
        row = cur.fetchone()
        municipio = row[0] if row else None

        hazards: dict[str, bool] = {}
        for key, table in hazard_layers.items():
            cur.execute(f'SELECT EXISTS(SELECT 1 FROM "{table}" WHERE ST_Intersects(geom, {pt}))', (lng, lat))
            hazards[key] = bool(cur.fetchone()[0])
    return {"municipio": municipio, "hazards": hazards}


def layer_geojson(name: str) -> dict[str, Any] | None:
    """Return one layer as a GeoJSON FeatureCollection, simplified + capped.

    Returns None if the layer isn't in the catalog (also the whitelist check).
    """
    with _conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT geometry_type FROM spatial_layers WHERE layer_name = %s", (name,))
        row = cur.fetchone()
        if row is None:
            return None
        geom_type = row[0]
        tol = _SIMPLIFY.get(geom_type)
        geom_expr = f"ST_SimplifyPreserveTopology(geom, {tol})" if tol else "geom"
        # name is whitelisted above (must exist in spatial_layers), safe to interpolate.
        sql = f"""
            SELECT jsonb_build_object(
                'type', 'FeatureCollection',
                'features', COALESCE(jsonb_agg(jsonb_build_object(
                    'type', 'Feature',
                    'geometry', ST_AsGeoJSON({geom_expr})::jsonb,
                    'properties', jsonb_build_object('id', id)
                )), '[]'::jsonb)
            )
            FROM (SELECT id, geom FROM "{name}" WHERE geom IS NOT NULL LIMIT {_MAX_FEATURES}) s
        """
        cur.execute(sql)
        return cur.fetchone()[0]
