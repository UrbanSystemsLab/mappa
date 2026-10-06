"""What the map knows about a place: a clicked point, and finding a place by name.

This file used to hold three more things, all removed:

  - a hand-written list of "facility" layers (schools, hospitals, shelters,
    roads) with their table names, used to count features - a second copy of
    what spatial_ops already does from the layer roles
  - the GeoJSON layer endpoint and the ten-layer list, which read a table that
    held only the first layers loaded by hand and that the page no longer calls
  - its own database connections, one opened per call, outside the shared pool

What a click checks now comes from the layer_roles table, so adding a hazard to
the click is a row in data/layer_roles.csv, not a code change.
"""

from __future__ import annotations

from typing import Any

from . import db

_POINT = "ST_SetSRID(ST_MakePoint(%s, %s), 4326)"


def locate(lng: float, lat: float) -> dict[str, Any]:
    """Which municipality a point is in, and which of the click-checked layers it
    falls inside.

    Each result names its layer as the registry does, in both languages, so the
    popup and the assistant both say what was checked rather than a code. These
    are facts about one spot - the assistant is told so explicitly.
    """
    from .spatial_ops import roles

    checked = [(key, spec) for key, spec in roles().items() if spec["checked_on_click"]]
    with db.connection() as conn:
        cur = conn.cursor()
        cur.execute(
            f"SELECT name FROM reference_units WHERE unit_type = 'municipio' "
            f"AND ST_Intersects(geom, {_POINT}) LIMIT 1",
            (lng, lat),
        )
        row = cur.fetchone()
        hazards = []
        for key, spec in checked:
            # The table comes from the roles table, which only lists registered
            # layers - never from the request.
            cur.execute(
                f'SELECT EXISTS(SELECT 1 FROM "{spec["table"]}" WHERE ST_Intersects(geom, {_POINT}))',
                (lng, lat),
            )
            hazards.append(
                {
                    "key": key,
                    "name_es": spec["label_es"],
                    "name_en": spec["label_en"],
                    "inside": bool(cur.fetchone()[0]),
                }
            )
    return {"municipio": row[0] if row else None, "hazards": hazards}


def search_places(q: str, limit: int = 8) -> list[dict[str, Any]]:
    """Look up any named place - municipio, barrio or comunidad - and return its bounds.

    Accent- and case-insensitive: a resident typing "anasco" or "ANASCO" should
    find Añasco. Exact prefix matches sort first so the obvious answer is on top.
    """
    if not q or len(q.strip()) < 2:
        return []
    term = q.strip()
    with db.connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT name, unit_type, parent_name,
                   ST_XMin(g), ST_YMin(g), ST_XMax(g), ST_YMax(g)
            FROM (
              SELECT name, unit_type, parent_name, ST_Envelope(geom) AS g,
                     translate(lower(name),
                               'áéíóúñüÁÉÍÓÚÑÜ','aeiounuAEIOUNU') AS plain
              FROM reference_units
            ) t
            WHERE plain LIKE translate(lower(%s),'áéíóúñüÁÉÍÓÚÑÜ','aeiounuAEIOUNU') || '%%'
               OR plain LIKE '%%' || translate(lower(%s),'áéíóúñüÁÉÍÓÚÑÜ','aeiounuAEIOUNU') || '%%'
            ORDER BY (plain LIKE translate(lower(%s),'áéíóúñüÁÉÍÓÚÑÜ','aeiounuAEIOUNU') || '%%') DESC,
                     CASE unit_type WHEN 'municipio' THEN 0 WHEN 'barrio' THEN 1 ELSE 2 END,
                     name
            LIMIT %s
            """,
            (term, term, term, limit),
        )
        return [
            {
                "name": r[0],
                "type": r[1],
                # A barrio's name does not identify it - there are nine called
                # Buena Vista - so the list shows which municipality it is in.
                "parent": r[2],
                "label": f"{r[0]}, {r[2]}" if r[2] and r[1] != "municipio" else r[0],
                "bbox": [float(r[3]), float(r[4]), float(r[5]), float(r[6])],
            }
            for r in cur.fetchall()
        ]
