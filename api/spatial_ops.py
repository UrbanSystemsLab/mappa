"""Spatial analysis over the loaded layers: counts, overlays, proximity, coverage.

Half the question bank asks things no document can answer - how many schools sit
in a flood zone, what share of a municipality is protected, which facilities lie
within 500 metres of a river. Before this, the model answered them anyway from
whatever numbers happened to appear in the retrieved text. Asked how many schools
in Arecibo were in a flood zone or near a river, it replied "10", taken from a
table header reading "10 pies" and an address on "Carr. 10".

So every number here is computed in PostGIS against their layers, and a question
this module cannot answer returns nothing rather than a guess - the caller is
expected to decline instead of letting the model fill the gap.

Layer names are resolved through a fixed alias table and validated against
layer_registry before they reach SQL, so nothing user-typed is interpolated.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

from . import db

# Concepts a question can name, mapped to the layers actually loaded. A concept
# with several layers (flooding has two FEMA vintages) names the one to use by
# default and keeps the other reachable, because saying which map a number came
# from matters more than the number.
LAYERS: dict[str, dict[str, Any]] = {
    "schools": {
        "table": "layer_dotacional_educacion_escuelas_2021",
        "label_es": "escuelas públicas (2021)", "label_en": "public schools (2021)",
        "name_col": "escuela", "muni_col": "municipio",
        "words": ["escuela", "escuelas", "school", "schools", "colegio", "plantel"],
    },
    "hospitals": {
        "table": "layer_hospitales",
        "label_es": "hospitales y CDTs", "label_en": "hospitals and CDTs",
        "name_col": "nombre", "muni_col": "muni",
        "words": ["hospital", "hospitals", "cdt", "salud", "health", "clinica", "clínica"],
    },
    "shelters": {
        "table": "layer_refugios_2023",
        "label_es": "refugios de emergencia (2023)", "label_en": "emergency shelters (2023)",
        "name_col": "instalacio", "muni_col": "municipio",
        "words": ["refugio", "refugios", "shelter", "shelters", "evacuacion", "evacuación"],
    },
    "flood": {
        "table": "layer_g23_riesgo_inundacion_fema_firms_2009",
        "label_es": "zonas inundables FEMA (2009)", "label_en": "FEMA flood zones (2009)",
        "words": ["inundacion", "inundación", "inundable", "inundables", "flood", "flooding",
                  "flood zone", "zona inundable"],
    },
    "flood_02": {
        "table": "layer_g23_riesgo_inundacion_floodzone_0_2pct_seamless_2018",
        "label_es": "inundación 0.2% anual FEMA (2018)",
        "label_en": "0.2% annual chance flood, FEMA (2018)",
        "words": ["0.2", "0,2", "500 year", "500-year"],
    },
    "landslide": {
        "table": "layer_landsl_monroe_plus_slop50pct",
        "label_es": "susceptibilidad a deslizamientos",
        "label_en": "landslide susceptibility",
        "words": ["deslizamiento", "deslizamientos", "landslide", "landslides", "derrumbe"],
    },
    "tsunami": {
        "table": "layer_g15_riesgo_geol_areas_desalojo_tsunami_2003",
        "label_es": "zonas de desalojo por tsunami (2003)",
        "label_en": "tsunami evacuation zones (2003)",
        "words": ["tsunami", "maremoto"],
    },
    "rivers": {
        "table": "layer_g23_mapa_base_crim_ogp_hidrografia_2006",
        "label_es": "hidrografía (ríos y quebradas, 2006)",
        "label_en": "hydrography (rivers and streams, 2006)",
        "words": ["rio", "río", "rios", "ríos", "river", "rivers", "quebrada", "quebradas",
                  "stream", "streams", "cuerpo de agua"],
    },
    "wetlands": {
        "table": "layer_g23_humedales_prvi_wetlands_fws_2010",
        "label_es": "humedales (FWS, 2010)", "label_en": "wetlands (FWS, 2010)",
        "words": ["humedal", "humedales", "wetland", "wetlands", "mangle", "manglar"],
    },
    "protected": {
        "table": "layer_pacat_2018_areas_protegidas_terrestres",
        "label_es": "áreas protegidas terrestres (PACAT 2018)",
        "label_en": "terrestrial protected areas (PACAT 2018)",
        "words": ["area protegida", "área protegida", "areas protegidas", "áreas protegidas",
                  "protected", "reserva", "reservas", "reserve", "area natural",
                  "área natural", "areas naturales", "áreas naturales", "natural area"],
    },
    "agricultural_valleys": {
        "table": "layer_g13_conserv_valles_agricolas_regla_5_2014",
        "label_es": "valles agrícolas (Regla 5, 2014)",
        "label_en": "agricultural valleys (Rule 5, 2014)",
        "words": ["valle agricola", "valle agrícola", "valles agricolas", "valles agrícolas",
                  "agricultural valley", "reserva agricola", "reserva agrícola",
                  "agricultural reserve"],
    },
    "agricultural_corridor": {
        "table": "layer_corredor_agricola_de_project_exportfeatures",
        "label_es": "corredor agrícola", "label_en": "agricultural corridor",
        "words": ["corredor agricola", "corredor agrícola", "agricultural corridor",
                  "terreno agricola", "terreno agrícola", "agricultural land",
                  "suelo agricola", "suelo agrícola"],
    },
    "roads": {
        "table": "layer_carreteras_estatales_segmentadas_agosto_2021",
        "label_es": "carreteras estatales (2021)", "label_en": "state roads (2021)",
        "words": ["carretera", "carreteras", "road", "roads", "highway", "vial"],
    },
    "coastal_zone": {
        "table": "layer_g27_conserv_zona_costanera_2010",
        "label_es": "zona costanera (2010)", "label_en": "coastal zone (2010)",
        "words": ["costanera", "costa", "coastal", "coastline", "litoral"],
    },
    "land_use_plan": {
        "table": "layer_plan_uso_terrenos_2015",
        "label_es": "Plan de Uso de Terrenos (2015)",
        "label_en": "Land Use Plan (2015)",
        "words": ["plan de uso de terrenos", "land use plan", "put", "clasificacion de suelo",
                  "clasificación de suelo", "zonificacion", "zonificación", "zoning",
                  "uso de suelo", "uso del suelo", "land use"],
    },
}

# Layers a question can count features of. A polygon layer like flooding is
# something to be inside of, not something to count.
COUNTABLE = {"schools", "hospitals", "shelters"}


def _strip(text: str) -> str:
    t = unicodedata.normalize("NFKD", (text or "").lower())
    return "".join(c for c in t if not unicodedata.combining(c))


def detect_layers(question: str) -> list[str]:
    """Which concepts a question names, longest phrase first so 'zona inundable'
    wins over a bare 'zona'."""
    text = _strip(question)
    found = []
    for key, spec in LAYERS.items():
        if any(_strip(w) in text for w in spec["words"]):
            found.append(key)
    return found


def detect_distance(question: str) -> tuple[int, int] | None:
    """Metres and where the phrase sits, from 'within 500 meters' or 'a menos de 2 km'.

    The position matters: a question can ask for one layer by intersection and
    another by distance - "in flood zones or within 500 metres of a river" - and
    applying the distance to both would answer a question nobody asked.
    """
    text = _strip(question)
    m = re.search(r"(\d[\d,.]*)\s*(m|metro|metros|meter|meters)\b", text)
    if m:
        return int(float(m.group(1).replace(",", ""))), m.end()
    m = re.search(r"(\d[\d,.]*)\s*(km|kilometro|kilometros|kilometer|kilometers)\b", text)
    if m:
        return int(float(m.group(1).replace(",", "")) * 1000), m.end()
    return None


def _layer_position(question: str, key: str) -> int:
    """Where a concept is first named, or -1. Used to bind a distance to the layer
    it modifies, which in both languages is the one that follows it."""
    text = _strip(question)
    hits = [text.find(_strip(w)) for w in LAYERS[key]["words"] if _strip(w) in text]
    return min(hits) if hits else -1


def _table(key: str) -> str:
    """Resolve a concept to its table, confirming it is published first.

    The alias table is fixed in code, and this checks the layer is actually
    loaded, so a concept whose data never arrived returns nothing instead of
    producing a query against a table that does not exist.
    """
    spec = LAYERS.get(key)
    if not spec:
        raise KeyError(key)
    with db.connection() as conn:
        cur = conn.cursor()
        # 'loaded' counts here: the assistant can answer from a layer that the
        # map does not offer as a toggle.
        cur.execute("SELECT 1 FROM layer_registry WHERE table_name=%s "
                    "AND status IN ('published','loaded')", (spec["table"],))
        if cur.fetchone() is None:
            raise KeyError(f"{key} not loaded")
    return spec["table"]


def label(key: str, lang: str = "es") -> str:
    spec = LAYERS[key]
    return spec["label_es"] if lang == "es" else spec["label_en"]


def _region_clause(region: str | None) -> tuple[str, list[Any]]:
    """SQL fragment limiting to a municipio, plus its parameters."""
    if not region:
        return "", []
    return (" AND EXISTS (SELECT 1 FROM reference_units r WHERE r.unit_type='municipio' "
            "AND unaccent_fallback(lower(r.name)) = unaccent_fallback(lower(%s)) "
            "AND ST_Intersects(r.geom, f.geom))", [region])


def count_features(layer: str, region: str | None = None) -> dict[str, Any] | None:
    """How many features of a layer, island-wide or inside one municipio."""
    if layer not in COUNTABLE:
        return None
    table = _table(layer)
    clause, params = _region_clause(region)
    with db.connection() as conn:
        cur = conn.cursor()
        cur.execute("SET LOCAL statement_timeout='30s'")
        cur.execute(f'SELECT count(*) FROM "{table}" f WHERE f.geom IS NOT NULL{clause}', params)
        n = cur.fetchone()[0]
    return {"op": "count", "layer": layer, "region": region, "count": n}


def count_intersecting(layer: str, hazard: str, region: str | None = None) -> dict[str, Any] | None:
    """How many features of one layer fall inside another - schools in a flood zone.

    ST_Intersects against the hazard polygons, so the number is the overlay, not
    a figure copied out of a report.
    """
    if layer not in COUNTABLE:
        return None
    table, haz = _table(layer), _table(hazard)
    clause, params = _region_clause(region)
    with db.connection() as conn:
        cur = conn.cursor()
        cur.execute("SET LOCAL statement_timeout='60s'")
        cur.execute(
            f'SELECT count(*) FROM "{table}" f WHERE f.geom IS NOT NULL{clause} '
            f'AND EXISTS (SELECT 1 FROM "{haz}" h WHERE ST_Intersects(h.geom, f.geom))',
            params,
        )
        n = cur.fetchone()[0]
        cur.execute(f'SELECT count(*) FROM "{table}" f WHERE f.geom IS NOT NULL{clause}', params)
        total = cur.fetchone()[0]
    return {"op": "intersect", "layer": layer, "against": hazard, "region": region,
            "count": n, "total": total}


def count_within_distance(layer: str, other: str, metres: int,
                          region: str | None = None) -> dict[str, Any] | None:
    """How many features lie within N metres of another layer.

    Distance is measured on the geography type, so metres are real metres rather
    than degrees. The candidate set is cut down by the region first and by a
    bounding-box overlap second, so the expensive check runs on few rows.
    """
    if layer not in COUNTABLE:
        return None
    table, target = _table(layer), _table(other)
    clause, params = _region_clause(region)
    deg = metres / 111_320.0  # rough degrees, only to pre-filter by bounding box
    with db.connection() as conn:
        cur = conn.cursor()
        cur.execute("SET LOCAL statement_timeout='120s'")
        cur.execute(
            f'SELECT count(*) FROM "{table}" f WHERE f.geom IS NOT NULL{clause} '
            f'AND EXISTS (SELECT 1 FROM "{target}" t '
            f'  WHERE t.geom && ST_Expand(f.geom, {deg:.10f}) '
            f'    AND ST_DWithin(t.geom::geography, f.geom::geography, %s))',
            params + [metres],
        )
        n = cur.fetchone()[0]
        cur.execute(f'SELECT count(*) FROM "{table}" f WHERE f.geom IS NOT NULL{clause}', params)
        total = cur.fetchone()[0]
    return {"op": "within_distance", "layer": layer, "of": other, "metres": metres,
            "region": region, "count": n, "total": total}


def coverage_share(layer: str, region: str) -> dict[str, Any] | None:
    """What share of a municipio a polygon layer covers.

    Areas are measured on the geography type and returned in km², because a share
    computed in square degrees is wrong by a factor that changes with latitude.
    """
    table = _table(layer)
    with db.connection() as conn:
        cur = conn.cursor()
        cur.execute("SET LOCAL statement_timeout='120s'")
        # The overlapping pieces are unioned before their area is taken, so two
        # overlapping polygons of the same layer are not counted twice.
        cur.execute(
            f"""
            SELECT ST_Area(r.geom::geography) / 1e6,
                   COALESCE((
                       SELECT ST_Area(ST_Union(
                                  ST_Intersection(ST_MakeValid(l.geom), r.geom)
                              )::geography) / 1e6
                       FROM "{table}" l
                       WHERE l.geom IS NOT NULL AND ST_Intersects(l.geom, r.geom)
                   ), 0)
            FROM reference_units r
            WHERE r.unit_type = 'municipio'
              AND unaccent_fallback(lower(r.name)) = unaccent_fallback(lower(%s))
            """,
            (region,),
        )
        row = cur.fetchone()
    if not row:
        return None
    total_km2, covered_km2 = float(row[0]), float(row[1])
    return {"op": "coverage", "layer": layer, "region": region,
            "region_km2": round(total_km2, 1), "covered_km2": round(covered_km2, 1),
            "share": round(covered_km2 / total_km2, 4) if total_km2 else 0.0}


def nearest(layer: str, lng: float, lat: float, k: int = 3) -> dict[str, Any] | None:
    """The k nearest features to a point, with real distances in metres."""
    spec = LAYERS.get(layer)
    if not spec or not spec.get("name_col"):
        return None
    table = _table(layer)
    name_col, muni_col = spec["name_col"], spec.get("muni_col")
    extra = f', f."{muni_col}"' if muni_col else ", NULL"
    with db.connection() as conn:
        cur = conn.cursor()
        cur.execute("SET LOCAL statement_timeout='30s'")
        cur.execute(
            f'SELECT f."{name_col}"{extra}, '
            f'  ST_Distance(f.geom::geography, ST_SetSRID(ST_MakePoint(%s,%s),4326)::geography) '
            f'FROM "{table}" f WHERE f.geom IS NOT NULL '
            f'ORDER BY f.geom <-> ST_SetSRID(ST_MakePoint(%s,%s),4326) LIMIT %s',
            (lng, lat, lng, lat, k),
        )
        rows = cur.fetchall()
    return {"op": "nearest", "layer": layer, "results": [
        {"name": r[0], "municipio": r[1], "metres": round(float(r[2]))} for r in rows]}


def point_profile(lng: float, lat: float) -> dict[str, Any]:
    """Everything the loaded layers say about one point - what a map click asks."""
    hazards = ["flood", "flood_02", "landslide", "tsunami", "wetlands", "protected",
               "agricultural_valleys", "coastal_zone"]
    out: dict[str, Any] = {"op": "point", "lng": lng, "lat": lat, "in": [], "not_in": []}
    point = "ST_SetSRID(ST_MakePoint(%s,%s),4326)"
    with db.connection() as conn:
        cur = conn.cursor()
        cur.execute("SET LOCAL statement_timeout='45s'")
        cur.execute(f"SELECT name FROM reference_units WHERE unit_type='municipio' "
                    f"AND ST_Intersects(geom, {point}) LIMIT 1", (lng, lat))
        row = cur.fetchone()
        out["municipio"] = row[0] if row else None
        for key in hazards:
            try:
                table = _table(key)
            except KeyError:
                continue
            cur.execute(f'SELECT EXISTS(SELECT 1 FROM "{table}" WHERE ST_Intersects(geom, {point}))',
                        (lng, lat))
            (out["in"] if cur.fetchone()[0] else out["not_in"]).append(key)
    return out


# Phrases that make a question quantitative. These are the ones that used to be
# answered with a number lifted out of retrieved prose.
_COUNT_WORDS = ["cuantos", "cuantas", "how many", "number of", "cuántos", "cuántas"]
_SHARE_WORDS = ["que porcentaje", "qué porcentaje", "what percentage", "how much of",
                "que parte", "qué parte", "what share", "cuanto de", "cuánto de",
                "how much", "que proporcion", "qué proporción"]


def wants_number(question: str) -> bool:
    """Whether the question asks for a figure we must compute rather than narrate."""
    text = _strip(question)
    return any(_strip(w) in text for w in _COUNT_WORDS + _SHARE_WORDS)


def analyze(question: str, region: str | None = None,
            history: list[str] | None = None) -> list[dict[str, Any]]:
    """Run whatever spatial question this is, and return only what was computed.

    Returns an empty list when the question is quantitative but the layers cannot
    answer it. The caller uses that to decline, which is the whole point: the
    absence of a result has to travel, or the model fills the silence.
    """
    keys = detect_layers(question)
    # "How many of those are in a flood zone?" names the hazard but not the thing
    # being counted - the subject is in the previous turn. Without it the question
    # reads as uncountable and the answer declines, having just said there are 25.
    if not any(k in COUNTABLE for k in keys):
        for earlier in reversed(history or []):
            carried = [k for k in detect_layers(earlier) if k in COUNTABLE]
            if carried:
                keys = carried + keys
                break
    if not keys:
        return []
    dist = detect_distance(question)
    countable = [k for k in keys if k in COUNTABLE]
    others = [k for k in keys if k not in COUNTABLE]
    text = _strip(question)
    results: list[dict[str, Any]] = []

    # The distance applies to the layer named after it; every other layer in the
    # question is an overlay.
    by_distance: set[str] = set()
    if dist and others:
        metres, at = dist
        after = [(pos, k) for k in others if (pos := _layer_position(question, k)) >= at]
        by_distance = {min(after)[1]} if after else set(others)

    try:
        if countable and others:
            metres = dist[0] if dist else None
            for c in countable:
                for o in others:
                    r = (count_within_distance(c, o, metres, region)
                         if o in by_distance and metres
                         else count_intersecting(c, o, region))
                    if r:
                        results.append(r)
        elif countable:
            for c in countable:
                r = count_features(c, region)
                if r:
                    results.append(r)
        elif others and region and any(_strip(w) in text for w in _SHARE_WORDS):
            for o in others:
                r = coverage_share(o, region)
                if r:
                    results.append(r)
    except KeyError:
        # A concept whose layer is not loaded. Nothing computed, so nothing claimed.
        return results
    return results


def describe(results: list[dict[str, Any]], lang: str = "es") -> list[str]:
    """One plain line per computed result, naming the layer the number came from."""
    out = []
    for r in results:
        lay = label(r["layer"], lang)
        where = r.get("region") or ("Puerto Rico")
        if r["op"] == "count":
            out.append(f"{r['count']} {lay} en {where}" if lang == "es"
                       else f"{r['count']} {lay} in {where}")
        elif r["op"] == "intersect":
            against = label(r["against"], lang)
            out.append(
                f"{r['count']} de {r['total']} {lay} en {where} intersecan {against}"
                if lang == "es" else
                f"{r['count']} of {r['total']} {lay} in {where} intersect {against}")
        elif r["op"] == "within_distance":
            of = label(r["of"], lang)
            out.append(
                f"{r['count']} de {r['total']} {lay} en {where} están a "
                f"{r['metres']} m o menos de {of}"
                if lang == "es" else
                f"{r['count']} of {r['total']} {lay} in {where} are within "
                f"{r['metres']} m of {of}")
        elif r["op"] == "coverage":
            out.append(
                f"{r['covered_km2']} km² de {where} ({r['region_km2']} km² en total, "
                f"{r['share']:.1%}) están cubiertos por {lay}"
                if lang == "es" else
                f"{r['covered_km2']} km² of {where} ({r['region_km2']} km² total, "
                f"{r['share']:.1%}) is covered by {lay}")
    return out


def suggested_layer_ids(question: str) -> list[str]:
    """Catalog IDs of the layers a question is about, so the map can show them.

    The frontend used to match on a layer's theme, a field almost every layer
    loaded from their GeoPackage leaves empty, so asking about flooding turned
    nothing on. Resolving concept -> table -> catalog ID uses the registry, which
    every loaded layer has a row in.
    """
    keys = detect_layers(question)
    if not keys:
        return []
    tables = [LAYERS[k]["table"] for k in keys]
    with db.connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT id FROM layer_registry WHERE status='published' "
            "AND table_name = ANY(%s)",
            (tables,),
        )
        return [r[0] for r in cur.fetchall()]
