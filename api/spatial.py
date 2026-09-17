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

# Simplification tolerance in degrees by geometry type; points unchanged. Bigger =
# smaller/faster payloads (island-wide overview doesn't need street-level precision).
_SIMPLIFY = {"MultiPolygon": 0.0009, "MultiLineString": 0.0005}
_MAX_FEATURES = 6000

# In-memory cache of built layer GeoJSON — layers rarely change, so this makes
# repeat toggles instant instead of re-querying PostGIS each time.
_LAYER_CACHE: dict[str, Any] = {}

# Per-layer (name column, subtitle column) so features carry a label for click popups.
_NAME_COLUMNS = {
    "layer_hospitales": ("nombre", "muni"),
    "layer_refugios_2023": ("instalacio", "municipio"),
    "layer_dotacional_educacion_escuelas_2021": ("escuela", "municipio"),
    "layer_g03_legales_municipios_2015": ("municipio", None),
}


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


# Facility layers we can answer "how many / where" questions about, from the map data.
FACILITY_LAYERS = {
    "school":   {"table": "layer_dotacional_educacion_escuelas_2021", "label": "public schools (2021)",
                 "kw": ["school", "schools", "escuela", "escuelas", "educacion", "education", "colegio"]},
    "hospital": {"table": "layer_hospitales", "label": "hospitals / CDTs",
                 "kw": ["hospital", "hospitals", "cdt", "salud", "health", "clinic", "clinica"]},
    "shelter":  {"table": "layer_refugios_2023", "label": "emergency shelters (2023)",
                 "kw": ["shelter", "shelters", "refugio", "refugios", "evacuation"]},
    "road":     {"table": "layer_carreteras_estatales_segmentadas_agosto_2021", "label": "state roads",
                 "kw": ["road", "roads", "carretera", "carreteras", "highway", "vial"]},
}


def _norm(text: str) -> str:
    import unicodedata
    t = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in t if not unicodedata.combining(c))


def detect_facilities(text: str) -> list[str]:
    t = _norm(text)
    return [k for k, v in FACILITY_LAYERS.items() if any(w in t for w in v["kw"])]


def facility_counts(text: str, municipio: str | None = None) -> dict[str, int]:
    """Count facility features the question asks about — within a municipio if given,
    else island-wide. Answers 'how many schools / hospitals' from real map data."""
    keys = detect_facilities(text)
    if not keys:
        return {}
    out: dict[str, int] = {}
    with _conn() as conn, conn.cursor() as cur:
        for k in keys:
            v = FACILITY_LAYERS[k]
            table = v["table"]  # from a fixed whitelist above, safe to interpolate
            if municipio:
                cur.execute(
                    f'SELECT count(*) FROM "{table}" f '
                    "JOIN reference_units r ON r.unit_type='municipio' "
                    "AND ST_Intersects(f.geom, r.geom) WHERE r.name ILIKE %s",
                    (municipio,),
                )
            else:
                cur.execute(f'SELECT count(*) FROM "{table}"')
            label = v["label"] + (f" in {municipio}" if municipio else " (Puerto Rico)")
            out[label] = cur.fetchone()[0]
    return out


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


def search_places(q: str, limit: int = 8) -> list[dict[str, Any]]:
    """Look up a municipio or barrio by name and return its bounds.

    Accent- and case-insensitive: a resident typing "anasco" or "ANASCO" should
    find Añasco. Exact prefix matches sort first so the obvious answer is on top.
    """
    if not q or len(q.strip()) < 2:
        return []
    term = q.strip()
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT name, unit_type,
                   ST_XMin(g), ST_YMin(g), ST_XMax(g), ST_YMax(g)
            FROM (
              SELECT name, unit_type, ST_Envelope(geom) AS g,
                     translate(lower(name),
                               'áéíóúñüÁÉÍÓÚÑÜ','aeiounuAEIOUNU') AS plain
              FROM reference_units
              WHERE unit_type IN ('municipio','barrio')
            ) t
            WHERE plain LIKE translate(lower(%s),'áéíóúñüÁÉÍÓÚÑÜ','aeiounuAEIOUNU') || '%%'
               OR plain LIKE '%%' || translate(lower(%s),'áéíóúñüÁÉÍÓÚÑÜ','aeiounuAEIOUNU') || '%%'
            ORDER BY (plain LIKE translate(lower(%s),'áéíóúñüÁÉÍÓÚÑÜ','aeiounuAEIOUNU') || '%%') DESC,
                     unit_type, name
            LIMIT %s
            """,
            (term, term, term, limit),
        )
        return [
            {"name": r[0], "type": r[1], "bbox": [float(r[2]), float(r[3]), float(r[4]), float(r[5])]}
            for r in cur.fetchall()
        ]


def municipio_bbox(name: str | None) -> list[float] | None:
    """Bounding box [west, south, east, north] of a municipio, so the map can fly to
    the place the chat is answering about. None if the name isn't a known municipio."""
    if not name:
        return None
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT ST_XMin(e), ST_YMin(e), ST_XMax(e), ST_YMax(e) FROM "
            "(SELECT ST_Extent(geom) e FROM reference_units "
            " WHERE unit_type='municipio' AND name ILIKE %s) t",
            (name,),
        )
        r = cur.fetchone()
        if r and r[0] is not None:
            return [float(r[0]), float(r[1]), float(r[2]), float(r[3])]
    return None


def layer_geojson(name: str) -> dict[str, Any] | None:
    """Return one layer as a GeoJSON FeatureCollection, simplified + capped.

    Returns None if the layer isn't in the catalog (also the whitelist check).
    """
    if name in _LAYER_CACHE:
        return _LAYER_CACHE[name]
    with _conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT geometry_type FROM spatial_layers WHERE layer_name = %s", (name,))
        row = cur.fetchone()
        if row is None:
            return None
        geom_type = row[0]
        tol = _SIMPLIFY.get(geom_type)
        geom_expr = f"ST_SimplifyPreserveTopology(geom, {tol})" if tol else "geom"
        # name/sub columns come from a fixed map (not user input), safe to interpolate.
        name_col, sub_col = _NAME_COLUMNS.get(name, (None, None))
        props = "'id', id"
        select_cols = "id, geom"
        if name_col:
            props += f", 'name', {name_col}"
            select_cols += f", {name_col}"
        if sub_col:
            props += f", 'sub', {sub_col}"
            select_cols += f", {sub_col}"
        # name is whitelisted above (must exist in spatial_layers), safe to interpolate.
        sql = f"""
            SELECT jsonb_build_object(
                'type', 'FeatureCollection',
                'features', COALESCE(jsonb_agg(jsonb_build_object(
                    'type', 'Feature',
                    'geometry', ST_AsGeoJSON({geom_expr})::jsonb,
                    'properties', jsonb_build_object({props})
                )), '[]'::jsonb)
            )
            FROM (SELECT {select_cols} FROM "{name}" WHERE geom IS NOT NULL LIMIT {_MAX_FEATURES}) s
        """
        cur.execute(sql)
        gj = cur.fetchone()[0]
    _LAYER_CACHE[name] = gj
    return gj
