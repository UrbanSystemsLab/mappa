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
import time
import unicodedata
from typing import Any

from . import db, places
from .places import Place

# Concepts a question can name, mapped to the layers actually loaded. A concept
# with several layers (flooding has two FEMA vintages) names the one to use by
# default and keeps the other reachable, because saying which map a number came
# from matters more than the number.
# Which layer does which job - 'flood' is the layer flood questions are answered
# from, 'schools' the one schools are counted in. This was a hand-written list of
# fifteen tables here, with a second in spatial.py and a third in retrieval.py,
# so changing a layer meant changing code. It is now the layer_roles table, filled
# from data/layer_roles.csv by pipelines/apply_layer_roles.
#
# Read once and kept for a few minutes: it changes when someone edits the file,
# not between one question and the next.
ROLE_CACHE_SECONDS = 300
_roles: dict[str, dict[str, Any]] | None = None
_roles_read_at = 0.0


def roles() -> dict[str, dict[str, Any]]:
    """Every role, with the live layer that fills it. A role whose layer is not
    loaded is left out, so nothing queries a table that is not there."""
    global _roles, _roles_read_at
    if _roles is not None and time.monotonic() - _roles_read_at < ROLE_CACHE_SECONDS:
        return _roles
    try:
        with db.connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """SELECT r.role, g.id, g.table_name, r.words, r.countable, r.checked_on_click,
                          r.name_col, r.muni_col, g.name_es, coalesce(g.name_en, g.name_es)
                   FROM layer_roles r JOIN layer_registry g ON g.id = r.layer_id
                   WHERE g.status IN ('published', 'loaded') AND g.table_name IS NOT NULL"""
            )
            rows = cur.fetchall()
    except Exception:
        # A database without the table yet - an older copy - answers by meaning
        # alone rather than failing every question.
        rows = []
    _roles = {
        role: {
            "id": lid,
            "table": table,
            "words": list(words or []),
            "countable": bool(countable),
            "checked_on_click": bool(on_click),
            "name_col": name_col,
            "muni_col": muni_col,
            "label_es": name_es,
            "label_en": name_en,
        }
        for role, lid, table, words, countable, on_click, name_col, muni_col, name_es, name_en in rows
    }
    _roles_read_at = time.monotonic()
    return _roles


def reset_roles() -> None:
    """Forget the cached roles - for tests, and after the roles file is applied."""
    global _roles
    _roles = None


def _strip(text: str) -> str:
    t = unicodedata.normalize("NFKD", (text or "").lower())
    return "".join(c for c in t if not unicodedata.combining(c))


def detect_layers(question: str) -> list[str]:
    """Which concepts a question names, longest phrase first so 'zona inundable'
    wins over a bare 'zona'."""
    text = _strip(question)
    found = []
    for key, spec in roles().items():
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
    hits = [text.find(_strip(w)) for w in roles()[key]["words"] if _strip(w) in text]
    return min(hits) if hits else -1


def _table(key: str) -> str:
    """The table that fills a role. Roles only list loaded layers, so a role
    whose data never arrived is simply absent."""
    spec = roles().get(key)
    if not spec:
        raise KeyError(key)
    return spec["table"]


def label(key: str, lang: str = "es") -> str:
    """The layer's name from the registry - La Maraña's, not one written here."""
    spec = roles()[key]
    return spec["label_es"] if lang == "es" else spec["label_en"]


def _region_clause(region: Place | str | None) -> tuple[str, list[Any]]:
    """SQL fragment limiting to one place, plus its parameters.

    It scopes by the place's code, so a barrio or a comunidad works exactly as a
    municipality does. The old clause hard-coded unit_type='municipio' because a
    name was all it had to go on, which is why nothing smaller than a
    municipality could ever be asked about.
    """
    return places.scope_clause(region)


def _region_label(region: Place | str | None) -> str | None:
    """How a result names its place - "Santurce, San Juan", not "Santurce"."""
    if region is None:
        return None
    return region.label if isinstance(region, Place) else region


def _region_code(region: Place | str | None) -> str | None:
    if isinstance(region, Place):
        return region.unit_code
    resolved = places.municipio(region) if region else None
    return resolved.unit_code if resolved else None


def count_features(layer: str, region: Place | str | None = None) -> dict[str, Any] | None:
    """How many features of a layer, island-wide or inside one municipio."""
    if not roles().get(layer, {}).get("countable"):
        return None
    table = _table(layer)
    clause, params = _region_clause(region)
    with db.connection() as conn:
        cur = conn.cursor()
        cur.execute("SET LOCAL statement_timeout='30s'")
        cur.execute(f'SELECT count(*) FROM "{table}" f WHERE f.geom IS NOT NULL{clause}', params)
        n = cur.fetchone()[0]
    return {"op": "count", "layer": layer, "region": _region_label(region), "count": n}


def count_intersecting(
    layer: str, hazard: str, region: Place | str | None = None
) -> dict[str, Any] | None:
    """How many features of one layer fall inside another - schools in a flood zone.

    ST_Intersects against the hazard polygons, so the number is the overlay, not
    a figure copied out of a report.
    """
    if not roles().get(layer, {}).get("countable"):
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
    return {
        "op": "intersect",
        "layer": layer,
        "against": hazard,
        "region": _region_label(region),
        "count": n,
        "total": total,
    }


def count_within_distance(
    layer: str, other: str, metres: int, region: Place | str | None = None
) -> dict[str, Any] | None:
    """How many features lie within N metres of another layer.

    Distance is measured on the geography type, so metres are real metres rather
    than degrees. The candidate set is cut down by the region first and by a
    bounding-box overlap second, so the expensive check runs on few rows.
    """
    if not roles().get(layer, {}).get("countable"):
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
            f"  WHERE t.geom && ST_Expand(f.geom, {deg:.10f}) "
            f"    AND ST_DWithin(t.geom::geography, f.geom::geography, %s))",
            [*params, metres],
        )
        n = cur.fetchone()[0]
        cur.execute(f'SELECT count(*) FROM "{table}" f WHERE f.geom IS NOT NULL{clause}', params)
        total = cur.fetchone()[0]
    return {
        "op": "within_distance",
        "layer": layer,
        "of": other,
        "metres": metres,
        "region": _region_label(region),
        "count": n,
        "total": total,
    }


def coverage_share(layer: str, region: Place | str) -> dict[str, Any] | None:
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
            WHERE r.unit_code = %s
            """,
            (_region_code(region),),
        )
        row = cur.fetchone()
    if not row:
        return None
    total_km2, covered_km2 = float(row[0]), float(row[1])
    return {
        "op": "coverage",
        "layer": layer,
        "region": _region_label(region),
        "region_km2": round(total_km2, 1),
        "covered_km2": round(covered_km2, 1),
        "share": round(covered_km2 / total_km2, 4) if total_km2 else 0.0,
    }


_COUNT_WORDS = ["cuantos", "cuantas", "how many", "number of", "cuántos", "cuántas"]
_SHARE_WORDS = [
    "que porcentaje",
    "qué porcentaje",
    "what percentage",
    "how much of",
    "que parte",
    "qué parte",
    "what share",
    "cuanto de",
    "cuánto de",
    "how much",
    "que proporcion",
    "qué proporción",
]


def wants_number(question: str) -> bool:
    """Whether the question asks for a figure we must compute rather than narrate."""
    text = _strip(question)
    return any(_strip(w) in text for w in _COUNT_WORDS + _SHARE_WORDS)


def analyze(
    question: str, region: Place | str | None = None, history: list[str] | None = None
) -> list[dict[str, Any]]:
    """Run whatever spatial question this is, and return only what was computed.

    Returns an empty list when the question is quantitative but the layers cannot
    answer it. The caller uses that to decline, which is the whole point: the
    absence of a result has to travel, or the model fills the silence.
    """
    # Every layer the question is about: the named concepts first, then anything
    # else found by meaning. This is what lifted the reach from fifteen layers to
    # all 601 - a question about toll plazas or bird habitat no longer has to
    # appear in a dictionary someone maintains by hand.
    hits = resolve(question, region=region)

    # "How many of those are in a flood zone?" names the hazard but not the thing
    # being counted - the subject is in the previous turn. Without it the question
    # reads as uncountable and the answer declines, having just said there are 25.
    if not any(h["countable"] for h in hits):
        for earlier in reversed(history or []):
            carried = [h for h in resolve(earlier, region=region) if h["countable"]]
            if carried:
                hits = carried + hits
                break
    if not hits:
        return []

    dist = detect_distance(question)
    countable = [h for h in hits if h["countable"]]
    others = [h for h in hits if not h["countable"]]
    text = _strip(question)
    results: list[dict[str, Any]] = []

    # The distance applies to the layer named after it; every other layer in the
    # question is an overlay. Only alias concepts have known phrasings to locate,
    # so a semantically-found layer takes the distance only if nothing else can.
    by_distance: set[str] = set()
    if dist and others:
        metres, at = dist
        after = [
            (pos, h["table"])
            for h in others
            if h.get("concept") and (pos := _layer_position(question, h["concept"])) >= at
        ]
        by_distance = {min(after)[1]} if after else {h["table"] for h in others}

    # An overlay is only wanted when the question asks to be inside something.
    # Without this, "how many fire hydrants are in Ponce?" paired hydrants against
    # a forestry-slope layer that merely scored well, and answered a question
    # nobody asked. A bare count is the safer reading of a bare question.
    overlay_wanted = bool(dist) or any(
        _strip(w) in text
        for w in [
            "inside",
            "within",
            "in a",
            "in the",
            "intersect",
            "overlap",
            "exposed",
            "affected",
            "dentro",
            "en zona",
            "en area",
            "en área",
            "en la zona",
            "intersecan",
            "expuest",
            "afectad",
        ]
    )
    # Coverage is a different question - "what share of X is Y" - and it needs
    # the polygon layer even though it asks about no overlay. Clearing the list
    # unconditionally silently broke it.
    asks_share = any(_strip(w) in text for w in _SHARE_WORDS)
    if not overlay_wanted and not asks_share:
        others = []

    try:
        if countable and others:
            metres = dist[0] if dist else None
            for c in countable[:1]:
                for o in others[:1]:
                    if o["table"] in by_distance and metres:
                        r = _within_distance_tables(c, o, metres, region)
                    else:
                        hit, total = intersect_tables(c["table"], o["table"], region)
                        r = {
                            "op": "intersect",
                            "layer": c["label"],
                            "against": o["label"],
                            "region": _region_label(region),
                            "count": hit,
                            "total": total,
                        }
                    if r:
                        results.append(r)
        elif countable:
            for c in countable[:1]:
                results.append(
                    {
                        "op": "count",
                        "layer": c["label"],
                        "region": _region_label(region),
                        "count": count_in_table(c["table"], region),
                    }
                )
        elif others and region and any(_strip(w) in text for w in _SHARE_WORDS):
            for o in others[:1]:
                r = _coverage_table(o, region)
                if r:
                    results.append(r)
    except Exception:
        # A layer that cannot be queried claims nothing, rather than guessing.
        return results
    return results


def _within_distance_tables(
    c: dict, o: dict, metres: int, region: Place | str | None
) -> dict[str, Any]:
    clause, params = _region_clause(region)
    deg = metres / 111_320.0
    with db.connection() as conn:
        cur = conn.cursor()
        cur.execute("SET LOCAL statement_timeout='120s'")
        cur.execute(
            f'SELECT count(*) FROM "{c["table"]}" f WHERE f.geom IS NOT NULL{clause} '
            f'AND EXISTS (SELECT 1 FROM "{o["table"]}" t '
            f"  WHERE t.geom && ST_Expand(f.geom, {deg:.10f}) "
            f"    AND ST_DWithin(t.geom::geography, f.geom::geography, %s))",
            [*params, metres],
        )
        hit = cur.fetchone()[0]
        cur.execute(
            f'SELECT count(*) FROM "{c["table"]}" f WHERE f.geom IS NOT NULL{clause}', params
        )
        total = cur.fetchone()[0]
    return {
        "op": "within_distance",
        "layer": c["label"],
        "of": o["label"],
        "metres": metres,
        "region": _region_label(region),
        "count": hit,
        "total": total,
    }


def _coverage_table(o: dict, region: Place | str) -> dict[str, Any] | None:
    with db.connection() as conn:
        cur = conn.cursor()
        cur.execute("SET LOCAL statement_timeout='180s'")
        cur.execute(
            f"""
            SELECT ST_Area(r.geom::geography) / 1e6,
                   COALESCE((SELECT ST_Area(ST_Union(
                                 ST_Intersection(ST_MakeValid(ST_Force2D(l.geom)),
                                                 r.geom))::geography) / 1e6
                             FROM "{o["table"]}" l
                             WHERE l.geom IS NOT NULL AND ST_Intersects(l.geom, r.geom)), 0)
            FROM reference_units r
            WHERE r.unit_code = %s
        """,
            (_region_code(region),),
        )
        row = cur.fetchone()
    if not row:
        return None
    total, covered = float(row[0]), float(row[1])
    return {
        "op": "coverage",
        "layer": o["label"],
        "region": _region_label(region),
        "region_km2": round(total, 1),
        "covered_km2": round(covered, 1),
        "share": round(covered / total, 4) if total else 0.0,
    }


def describe(results: list[dict[str, Any]], lang: str = "es") -> list[str]:
    """One plain line per computed result, naming the layer the number came from."""
    out = []
    for r in results:
        # analyze() now puts the layer's own name here rather than a concept key,
        # because most layers no longer have one - they are found by meaning.
        lay = r["layer"]
        where = r.get("region") or ("Puerto Rico")
        if r["op"] == "count":
            out.append(
                f"{r['count']} {lay} en {where}"
                if lang == "es"
                else f"{r['count']} {lay} in {where}"
            )
        elif r["op"] == "intersect":
            against = r["against"]
            out.append(
                f"{r['count']} de {r['total']} {lay} en {where} intersecan {against}"
                if lang == "es"
                else f"{r['count']} of {r['total']} {lay} in {where} intersect {against}"
            )
        elif r["op"] == "within_distance":
            of = r["of"]
            out.append(
                f"{r['count']} de {r['total']} {lay} en {where} están a "
                f"{r['metres']} m o menos de {of}"
                if lang == "es"
                else f"{r['count']} of {r['total']} {lay} in {where} are within "
                f"{r['metres']} m of {of}"
            )
        elif r["op"] == "coverage":
            out.append(
                f"{r['covered_km2']} km² de {where} ({r['region_km2']} km² en total, "
                f"{r['share']:.1%}) están cubiertos por {lay}"
                if lang == "es"
                else f"{r['covered_km2']} km² of {where} ({r['region_km2']} km² total, "
                f"{r['share']:.1%}) is covered by {lay}"
            )
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
    ids = [roles()[k]["id"] for k in keys]
    with db.connection() as conn:
        cur = conn.cursor()
        # Only what the map can draw.
        cur.execute(
            "SELECT id FROM layer_registry WHERE status='published' AND id = ANY(%s)", (ids,)
        )
        return [r[0] for r in cur.fetchall()]


# ─────────────────────────────────────────────────────────────────────────────
# Finding layers by meaning rather than by dictionary
#
# Roles name about fifteen layers. There are 603 with data. The roles stay,
# because for the concepts that matter most - schools, flood zones, hospitals -
# we want the exact layer rather than whichever one scores highest today.
# Everything else is found by meaning.
# ─────────────────────────────────────────────────────────────────────────────

# Below this, the nearest layer is not actually about what was asked. Boundary
# layers - barrios, comunidades - sit around 0.45 against almost any question,
# because every question mentions a place, so the floor has to clear them.
MIN_LAYER_SCORE = 0.45
# And a layer much weaker than the best match is not what was meant either, even
# if it clears the floor.
RELATIVE_DROP = 0.10

# A layer with more features than this is a basemap-like surface - parcels,
# contours, land cover. Counting its features answers nothing a person asked.
COUNTABLE_CEILING = 60_000


def _without_place(question: str, region: Place | str | None) -> str:
    """The question with the place name removed.

    "How many wells are in Arecibo?" matched 'tipo de suelo arecibo' ahead of
    'pozos', because the place name is a third of the sentence and several layers
    carry a municipality in their name. The place is handled separately - it
    becomes the region filter - so it only adds noise to the layer match.
    """
    if not region:
        return question
    name = region.name if isinstance(region, Place) else region
    pattern = re.sub(r"\s+", r"\\s+", re.escape(name))
    cleaned = re.sub(pattern, " ", question, flags=re.I)
    cleaned = re.sub(r"\b(in|en|de|del|for|para|at)\s*$", "", cleaned.strip(), flags=re.I)
    return cleaned.strip() or question


def _question_vector(question: str) -> str:
    from .retrieval import _get_query_model, _vector_literal

    return _vector_literal(
        _get_query_model().encode([question], normalize_embeddings=True, show_progress_bar=False)[0]
    )


def find_layers(
    question: str, limit: int = 4, loaded_only: bool = True, region: Place | str | None = None
) -> list[dict[str, Any]]:
    """Layers whose meaning is closest to the question.

    Returns the registry row rather than a concept key, so a caller can work with
    any of the 601 layers instead of the fifteen that happen to be named above.
    """
    lit = _question_vector(_without_place(question, region))
    where = "embedding IS NOT NULL AND table_name IS NOT NULL"
    if loaded_only:
        where += " AND status IN ('published','loaded')"
    with db.connection() as conn:
        cur = conn.cursor()
        cur.execute("SET LOCAL statement_timeout='20s'")
        cur.execute(
            f"""
            SELECT id, table_name, name_es, geometry_type, feature_count,
                   1 - (embedding <=> %s::vector) AS score
            FROM layer_registry WHERE {where}
            ORDER BY embedding <=> %s::vector LIMIT %s
        """,
            (lit, lit, limit),
        )
        rows = cur.fetchall()
    hits = [
        {
            "id": r[0],
            "table": r[1],
            "label": r[2],
            "geometry": r[3] or "",
            "features": r[4] or 0,
            "score": float(r[5]),
        }
        for r in rows
        if float(r[5]) >= MIN_LAYER_SCORE
    ]
    if not hits:
        return []

    best = hits[0]["score"]
    return [h for h in hits if best - h["score"] <= RELATIVE_DROP]


def resolve(
    question: str, limit: int = 4, region: Place | str | None = None
) -> list[dict[str, Any]]:
    """Every layer the question is about, named ones first.

    A concept in the alias table is used as given - it was written down because
    the exact layer matters. Anything else comes from meaning, and a layer
    already matched by alias is not offered twice.
    """
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for key in detect_layers(question):
        spec = roles()[key]
        table = spec["table"]
        out.append(
            {
                "id": key,
                "table": table,
                "label": spec["label_es"],
                "geometry": "",
                "features": 0,
                "score": 1.0,
                "concept": key,
                "countable": spec["countable"],
            }
        )
        seen.add(table)
    for hit in find_layers(question, limit=limit, region=region):
        if hit["table"] in seen:
            continue
        hit["concept"] = None
        # Points and small polygon sets are things you count; a 500,000-polygon
        # surface is something you are inside of.
        hit["countable"] = (
            "point" in hit["geometry"].lower() and 0 < hit["features"] <= COUNTABLE_CEILING
        )
        out.append(hit)
        seen.add(hit["table"])
    return out


def count_in_table(table: str, region: Place | str | None = None) -> int:
    """Features of any loaded layer, by table name rather than concept."""
    clause, params = _region_clause(region)
    with db.connection() as conn:
        cur = conn.cursor()
        cur.execute("SET LOCAL statement_timeout='45s'")
        cur.execute(f'SELECT count(*) FROM "{table}" f WHERE f.geom IS NOT NULL{clause}', params)
        return cur.fetchone()[0]


def intersect_tables(
    table: str, against: str, region: Place | str | None = None
) -> tuple[int, int]:
    """How many features of one table fall inside another."""
    clause, params = _region_clause(region)
    with db.connection() as conn:
        cur = conn.cursor()
        cur.execute("SET LOCAL statement_timeout='90s'")
        cur.execute(
            f'SELECT count(*) FROM "{table}" f WHERE f.geom IS NOT NULL{clause} '
            f'AND EXISTS (SELECT 1 FROM "{against}" h WHERE ST_Intersects(h.geom, f.geom))',
            params,
        )
        hit = cur.fetchone()[0]
        cur.execute(f'SELECT count(*) FROM "{table}" f WHERE f.geom IS NOT NULL{clause}', params)
        return hit, cur.fetchone()[0]
