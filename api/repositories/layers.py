"""Map layers: finding them by meaning, and the roles some of them play.

`layer_registry` is the catalogue; each row with data names the table holding its
shapes. A layer is only ever reached through its registry id, so no table name
from a request or a model reaches SQL.

Roles (`layer_roles`, from data/layer_roles.csv) mark the layer that answers a
kind of question - "flood" is the FEMA 2009 flood zones - and which layers a
map click checks.
"""

from __future__ import annotations

from dataclasses import dataclass

from .. import db
from ..cache import cached
from ..embeddings import vector

# Candidates below this are not about the topic at all. The model chooses among
# the rest from their names, so this is a floor, not a judgement.
MIN_LAYER_SCORE = 0.30

_COLUMNS = (
    "id, table_name, name_es, coalesce(name_en, name_es), geometry_type, feature_count, status, "
    "source_agency, vintage_year, gis_id"
)
_N = 10  # columns in _COLUMNS
_LIVE = "status IN ('published', 'loaded') AND table_name IS NOT NULL"


@dataclass(frozen=True, slots=True)
class Layer:
    id: str
    table: str
    name_es: str
    name_en: str
    geometry: str
    features: int
    status: str
    agency: str | None = None  # who made the data, as their inventory records it
    year: int | None = None
    reference: str | None = None  # their GIS inventory ID, e.g. GIS-328

    @property
    def is_area(self) -> bool:
        return "polygon" in self.geometry.lower()

    @property
    def on_map(self) -> bool:
        return self.status == "published"

    def name(self, lang: str) -> str:
        return self.name_es if lang == "es" else self.name_en


def _row(r: tuple) -> Layer:
    return Layer(
        r[0],
        r[1],
        r[2] or r[1],
        r[3] or r[2] or r[1],
        r[4] or "",
        r[5] or 0,
        r[6],
        r[7] or None,
        int(r[8]) if r[8] else None,
        r[9] or None,
    )


def get(layer_id: str) -> Layer | None:
    """A layer that has data, by registry id."""
    with db.connection() as conn:
        cur = conn.cursor()
        cur.execute(f"SELECT {_COLUMNS} FROM layer_registry WHERE id = %s AND {_LIVE}", (layer_id,))
        row = cur.fetchone()
    return _row(row) if row else None


def search(topic: str, limit: int = 8) -> list[tuple[Layer, float]]:
    """Layers whose name and description are closest in meaning to the topic."""
    lit = vector(topic)
    with db.connection() as conn:
        cur = conn.cursor()
        cur.execute(
            f"SELECT {_COLUMNS}, 1 - (embedding <=> %s::vector) FROM layer_registry "
            f"WHERE embedding IS NOT NULL AND {_LIVE} "
            f"ORDER BY embedding <=> %s::vector LIMIT %s",
            (lit, lit, limit),
        )
        rows = [(_row(r[:_N]), float(r[_N])) for r in cur.fetchall()]
    return [(layer, s) for layer, s in rows if s >= MIN_LAYER_SCORE]


@dataclass(frozen=True, slots=True)
class Role:
    name: str
    layer: Layer
    checked_on_click: bool
    words: tuple[str, ...] = ()


@cached(seconds=300)
def roles() -> dict[str, Role]:
    """Every role whose layer has data. Re-read every few minutes, so editing
    the roles file and applying it takes effect without a restart."""
    with db.connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """SELECT r.role, r.checked_on_click, r.words,
                      g.id, g.table_name, g.name_es, coalesce(g.name_en, g.name_es),
                      g.geometry_type, g.feature_count, g.status,
                      g.source_agency, g.vintage_year, g.gis_id
               FROM layer_roles r JOIN layer_registry g ON g.id = r.layer_id
               WHERE g.status IN ('published', 'loaded') AND g.table_name IS NOT NULL"""
        )
        return {
            role: Role(role, _row(tuple(rest)), bool(on_click), tuple(words or ()))
            for role, on_click, words, *rest in cur.fetchall()
        }


def role_of(layer: Layer) -> str | None:
    return next((r.name for r in roles().values() if r.layer.id == layer.id), None)
