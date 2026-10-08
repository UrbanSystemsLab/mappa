"""Named places - municipios, barrios, comunidades - and their boundaries.

The gazetteer is `reference_units`: 1,693 places, each with a boundary and, below
the municipio level, the municipio it sits in. A place is identified by its
`unit_code`, which is what spatial queries scope by.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from typing import Any

from .. import db
from ..cache import cached

_POINT = "ST_SetSRID(ST_MakePoint(%s, %s), 4326)"


def plain(text: str | None) -> str:
    """Lower case, accents removed: "Añasco" and "anasco" compare equal."""
    t = unicodedata.normalize("NFKD", (text or "").lower())
    return "".join(c for c in t if not unicodedata.combining(c)).strip()


@dataclass(frozen=True, slots=True)
class Place:
    unit_code: str
    name: str
    unit_type: str  # municipio | barrio | comunidad
    parent_name: str | None

    @property
    def municipio(self) -> str | None:
        """The municipio this is, or is in. Documents are filed by municipio."""
        return self.name if self.unit_type == "municipio" else self.parent_name

    @property
    def label(self) -> str:
        """How to name it to a reader: a barrio with its municipio."""
        if self.unit_type == "municipio" or not self.parent_name:
            return self.name
        return f"{self.name}, {self.parent_name}"


@cached()
def _all() -> list[Place]:
    with db.connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT unit_code, name, unit_type, parent_name FROM reference_units "
            "WHERE name IS NOT NULL"
        )
        return [Place(*row) for row in cur.fetchall()]


def lookup(name: str, municipio: str | None = None) -> list[Place]:
    """Places with exactly this name, municipios first.

    Several places can share a name - 74 municipios have a Barrio Pueblo - so the
    caller gets all of them unless `municipio` narrows it.
    """
    want, within = plain(name), plain(municipio)
    found = [p for p in _all() if plain(p.name) == want]
    if within:
        found = [p for p in found if plain(p.municipio) == within]
    return sorted(found, key=lambda p: (p.unit_type != "municipio", p.label))


def by_code(unit_code: str) -> Place | None:
    return next((p for p in _all() if p.unit_code == unit_code), None)


def from_selection(label: str | None) -> Place | None:
    """A place picked in the search box, given back as it was shown: "Santurce, San Juan"."""
    if not label:
        return None
    name, _, municipio = label.partition(",")
    found = lookup(name, municipio.strip() or None)
    return found[0] if found else None


def search(term: str, limit: int = 8) -> list[dict[str, Any]]:
    """Places whose name starts with or contains `term`, for a search box."""
    if not term or len(term.strip()) < 2:
        return []
    with db.connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT name, unit_type, parent_name, ST_XMin(g), ST_YMin(g), ST_XMax(g), ST_YMax(g)
            FROM (SELECT name, unit_type, parent_name, ST_Envelope(geom) AS g,
                         unaccent_fallback(lower(name)) AS plain
                  FROM reference_units) t
            WHERE plain LIKE '%%' || unaccent_fallback(lower(%s)) || '%%'
            ORDER BY (plain LIKE unaccent_fallback(lower(%s)) || '%%') DESC,
                     CASE unit_type WHEN 'municipio' THEN 0 WHEN 'barrio' THEN 1 ELSE 2 END, name
            LIMIT %s
            """,
            (term.strip(), term.strip(), limit),
        )
        rows = cur.fetchall()
    return [
        {
            "name": name,
            "type": kind,
            "parent": parent,
            "label": f"{name}, {parent}" if parent and kind != "municipio" else name,
            "bbox": [float(w), float(s), float(e), float(n)],
        }
        for name, kind, parent, w, s, e, n in rows
    ]


def bbox(place: Place | None) -> list[float] | None:
    """[west, south, east, north]."""
    if place is None:
        return None
    with db.connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT ST_XMin(e), ST_YMin(e), ST_XMax(e), ST_YMax(e) FROM "
            "(SELECT ST_Extent(geom) e FROM reference_units WHERE unit_code = %s) t",
            (place.unit_code,),
        )
        row = cur.fetchone()
    return [float(x) for x in row] if row and row[0] is not None else None


def scope(place: Place | None, alias: str = "f") -> tuple[str, list[str]]:
    """A SQL condition limiting table `alias` to features inside the place."""
    if place is None:
        return "", []
    return (
        f" AND EXISTS (SELECT 1 FROM reference_units r WHERE r.unit_code = %s "
        f"AND ST_Intersects(r.geom, {alias}.geom))",
        [place.unit_code],
    )


def municipio_at(lng: float, lat: float) -> str | None:
    with db.connection() as conn:
        cur = conn.cursor()
        cur.execute(
            f"SELECT name FROM reference_units WHERE unit_type = 'municipio' "
            f"AND ST_Intersects(geom, {_POINT}) LIMIT 1",
            (lng, lat),
        )
        row = cur.fetchone()
    return row[0] if row else None
