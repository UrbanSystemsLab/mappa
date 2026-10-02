"""Layer catalog — search, filter and describe layers from layer_registry.

Replaces the hardcoded LAYER_LABELS / THEME / CATEGORY dictionaries that used to
live in frontend/app.js. Everything the client needs to render the layer panel now
comes from the database, so adding a layer is a data operation rather than a code
change and a deploy — which is what makes 600 layers tractable, and what lets
La Maraña manage the catalog themselves after handoff.

Language is resolved server-side: the client asks for 'es' or 'en' and gets one
`name`, rather than receiving both and choosing.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

from . import db

# Their sheet spells five categories more than one way - Conservacion and
# Conservación, Limites geograficos and Limites_Geograficos - which would split
# one theme across two groups in the layer panel. Group on an accent- and
# punctuation-insensitive key and show the best-written variant, while each layer
# still reports their exact string so nothing they wrote is overwritten.
_CATEGORY_LABEL = {
    "conservacion": "Conservación",
    "desarrolloeconomico": "Desarrollo Económico",
    "geologia": "Geología",
    "hidrografia": "Hidrografía",
    "limitesgeograficos": "Límites geográficos",
    # Layers from their GeoPackage whose name does not match a single row on the
    # inventory sheet, so we do not know their category. Saying so beats a label
    # that sounds like a judgement on the data.
    "sinclasificar": "Otras capas",
}


def _category_key(name: str | None) -> str:
    text = unicodedata.normalize("NFKD", (name or "").lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "", text)


def canonical_category(name: str | None) -> str:
    """One display label per theme, regardless of how their sheet spelled it."""
    if not name:
        return "Sin clasificar"
    return _CATEGORY_LABEL.get(_category_key(name), name.replace("_", " "))


# Columns returned for a row in the layer list.
_LIST_COLS = """
    id, table_name, category, subcategory, theme, keywords,
    source_agency, source_inventory, source_url, vintage_year, license,
    metadata_status, geometry_type, feature_count, srid,
    min_zoom, max_zoom, label_column, sublabel_column, style,
    dataset_version, status, property_labels, value_labels
"""


def _row_to_layer(r: tuple, lang: str) -> dict[str, Any]:
    (lid, table, category, subcategory, theme, keywords, agency, inventory, src_url,
     year, license_, mstatus, gtype, fcount, srid, minz, maxz, label_col, sub_col,
     style, version, status, prop_labels, val_labels, name, description) = r
    return {
        "id": lid,
        "name": name,
        "description": description,
        "category": canonical_category(category),
        # Exactly what their inventory says, kept so the grouping above never
        # stands in for what they actually wrote.
        "category_source": category,
        "subcategory": subcategory,
        "theme": theme,
        "keywords": keywords or [],
        "source": {
            "agency": agency,
            "inventory": inventory,
            "url": src_url,
            "year": year,
            "license": license_,
            # La Maraña's own vocabulary: confirmed / inferred / reconstructed / unknown.
            "metadata_status": mstatus,
        },
        "geometry_type": gtype,
        "feature_count": fcount,
        "srid": srid,
        "min_zoom": minz,
        "max_zoom": maxz,
        "label_column": label_col,
        "sublabel_column": sub_col,
        "style": style or {},
        # Human field names and decoded values, so the UI never shows a user a raw
        # column like CLASIPUT or a bare code like SREP-EP.
        "property_labels": prop_labels or {},
        "value_labels": val_labels or {},
        "dataset_version": version,
        "status": status,
        # 'catalogued' means the layer is on La Maraña's inventory but its data is
        # not in the database yet. It is listed so the catalog reflects what they
        # actually hold, and it carries no tile URL, because there is nothing to
        # draw. The UI shows it as unavailable rather than as a toggle that fails.
        "available": bool(table) and status == "published",
        # Queryable by the assistant even when it is not a map toggle.
        "queryable": bool(table) and status in ("published", "loaded"),
        # Version in the path means a republished layer gets fresh tile URLs, so
        # cached tiles are invalidated without purging the CDN.
        "tiles_url": (f"/tiles/{table}/{{z}}/{{x}}/{{y}}.mvt?v={version}" if table else None),
    }


def _lang_cols(lang: str) -> str:
    return ("name_es AS name, description_es AS description" if lang == "es"
            else "COALESCE(name_en, name_es) AS name, "
                 "COALESCE(description_en, description_es) AS description")


def list_layers(
    lang: str = "es",
    q: str | None = None,
    category: str | None = None,
    include_drafts: bool = False,
    available_only: bool = False,
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    """Search / filter the catalog. Returns {total, limit, offset, layers}."""
    lang = "es" if lang == "es" else "en"
    if available_only:
        # What the map panel asks for: layers it can actually draw.
        where = ["status = 'published'"]
    elif include_drafts:
        where = ["status <> 'hidden'"]
    else:
        # 'loaded' means the data is in the database and the assistant can query
        # it, but it is not offered as a map toggle - La Maraña chooses which
        # are promoted to 'published'.
        where = ["status IN ('published','loaded','catalogued')"]
    params: dict[str, Any] = {}

    if category:
        where.append("regexp_replace(lower(translate(category,"
                     "'áéíóúñüÁÉÍÓÚÑÜ','aeiounuAEIOUNU')), '[^a-z0-9]+', '', 'g') "
                     "= %(category)s")
        params["category"] = _category_key(category)
    if q:
        # Prose match OR keyword-array match, so "flood" finds a layer whose only
        # English signal is a keyword.
        where.append("""(
            to_tsvector('simple',
                coalesce(name_es,'') || ' ' || coalesce(name_en,'') || ' ' ||
                coalesce(description_es,'') || ' ' || coalesce(description_en,'') || ' ' ||
                coalesce(source_agency,'')) @@ plainto_tsquery('simple', %(q)s)
            OR EXISTS (SELECT 1 FROM unnest(keywords) k WHERE k ILIKE %(qlike)s)
            OR name_es ILIKE %(qlike)s OR name_en ILIKE %(qlike)s
        )""")
        params["q"] = q
        params["qlike"] = f"%{q}%"

    wsql = " AND ".join(where)
    params.update({"limit": limit, "offset": offset})

    with db.connection() as conn:
        cur = conn.cursor()
        cur.execute(f"SELECT count(*) FROM layer_registry WHERE {wsql}", params)
        total = cur.fetchone()[0]
        cur.execute(
            f"SELECT {_LIST_COLS}, {_lang_cols(lang)} FROM layer_registry "
            f"WHERE {wsql} ORDER BY (status = 'published') DESC, category, "
            f"{'name_es' if lang == 'es' else 'COALESCE(name_en, name_es)'} "
            f"LIMIT %(limit)s OFFSET %(offset)s",
            params,
        )
        layers = [_row_to_layer(r, lang) for r in cur.fetchall()]
    return {"total": total, "limit": limit, "offset": offset, "layers": layers}


def get_layer(layer_id: str, lang: str = "es") -> dict[str, Any] | None:
    """Full metadata for one layer — powers the per-layer metadata popup."""
    lang = "es" if lang == "es" else "en"
    with db.connection() as conn:
        cur = conn.cursor()
        cur.execute(
            f"SELECT {_LIST_COLS}, {_lang_cols(lang)} FROM layer_registry WHERE id = %s",
            (layer_id,),
        )
        row = cur.fetchone()
    return _row_to_layer(row, lang) if row else None


def categories(lang: str = "es", available_only: bool = False) -> list[dict[str, Any]]:
    """Category facets with counts, for grouping the layer panel."""
    with db.connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT category, count(*) FILTER (WHERE status = 'published'), count(*) "
            "FROM layer_registry WHERE status = 'published' "
            "GROUP BY category" if available_only else
            "SELECT category, count(*) FILTER (WHERE status = 'published'), count(*) "
            "FROM layer_registry WHERE status IN ('published','catalogued') "
            "GROUP BY category"
        )
        merged: dict[str, dict[str, Any]] = {}
        for cat, available, total in cur.fetchall():
            label = canonical_category(cat)
            row = merged.setdefault(label, {"category": label, "available": 0, "count": 0})
            row["available"] += available
            row["count"] += total
        return sorted(merged.values(), key=lambda r: r["category"])


def tile_columns(table_name: str) -> tuple[str | None, str | None]:
    """label/sublabel columns for a layer's tiles, from the registry rather than a
    hardcoded map in the tile service."""
    with db.connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT label_column, sublabel_column FROM layer_registry WHERE table_name = %s",
            (table_name,),
        )
        row = cur.fetchone()
    return (row[0], row[1]) if row else (None, None)
