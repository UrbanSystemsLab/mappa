"""Resolving the place a question is about.

`reference_units` held 78 municipalities, and every spatial function took a
place *name*. So the assistant could answer about a municipality and nothing
smaller - a question about Santurce or Caño Martín Peña had nowhere to land,
even though both are on the map.

It now holds 1,693 places: 78 municipios, 902 barrios and 713 comunidades
especiales. Reaching them needs two problems solved first, and both are the
reason this is a module rather than a line of SQL.

**Names repeat.** There is a Barrio Pueblo in 74 of the 78 municipalities, nine
places called Buena Vista and five called Playa. A bare "Pueblo" names no single
place, so it is only accepted when the sentence also says which municipality.

**Names are ordinary words.** There is a barrio called Playa, one called Centro
and one called Costa. "¿Cuántos humedales hay cerca de la costa?" must not be
scoped to a barrio in Isabela and answered with confident precision - that is
the failure this project has been bitten by, a true-sounding number computed
over the wrong thing. Which names are ordinary words is measured from the corpus
by the gazetteer pipeline, not guessed here.

What comes out is a Place with a code, and spatial queries scope by that code
rather than by a name. A code identifies a barrio as readily as a municipality,
which is what makes everything below the municipality reachable at all.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from . import db

# A place name must stand as a word. Without this, "Mora" matches "Moravia" and
# every question containing "costa" matches barrio Costa in Isabela.
_EDGE = r"(?<![a-z0-9])"
_EDGE_END = r"(?![a-z0-9])"

# Words that mark the next noun as a place, so "barrio Playa" is accepted where
# bare "playa" is not.
_CUES = ("barrio", "bo.", "comunidad", "sector", "urbanizacion", "urb.")


def _strip(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in text if not unicodedata.combining(c))


@dataclass(frozen=True, slots=True)
class Place:
    """One named place, and the handle spatial queries scope by."""

    unit_code: str
    name: str
    unit_type: str
    parent_name: str | None
    common_word: bool = False

    @property
    def municipio(self) -> str | None:
        """The municipality this sits in - itself, if it is one.

        Documents are filed by municipality, so a question about a barrio still
        reads that municipality's plans.
        """
        return self.name if self.unit_type == "municipio" else self.parent_name

    @property
    def label(self) -> str:
        """How the answer names it. A barrio is named with its municipality,
        because on its own the name does not identify anywhere."""
        if self.unit_type == "municipio" or not self.parent_name:
            return self.name
        return f"{self.name}, {self.parent_name}"


_places: list[Place] | None = None
_by_name: dict[str, list[Place]] | None = None
_pattern: re.Pattern[str] | None = None


def _load() -> tuple[dict[str, list[Place]], re.Pattern[str]]:
    """Every place, once. 1,693 rows is small enough to hold and far cheaper
    than a query per question."""
    global _places, _by_name, _pattern
    if _by_name is not None and _pattern is not None:
        return _by_name, _pattern

    with db.connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT unit_code, name, unit_type, parent_name, "
            "COALESCE(common_word, false) FROM reference_units WHERE name IS NOT NULL"
        )
        rows = cur.fetchall()

    _places = [Place(*r) for r in rows]
    by_name: dict[str, list[Place]] = {}
    for p in _places:
        by_name.setdefault(_strip(p.name), []).append(p)

    # One pass over the question instead of 1,693. Longest first, so "San Juan"
    # is found before "Juan" would be.
    names = sorted(by_name, key=len, reverse=True)
    _pattern = re.compile(_EDGE + "(?:" + "|".join(re.escape(n) for n in names) + ")" + _EDGE_END)
    _by_name = by_name
    return _by_name, _pattern


def reset_cache() -> None:
    """Forget the loaded gazetteer - for tests, and after a reload."""
    global _places, _by_name, _pattern
    _places = _by_name = _pattern = None


def _part_of_a_longer_name(original: str, name: str) -> bool:
    """Whether the match sits inside a capitalised phrase the gazetteer does not have.

    "Caño Martín Peña" resolved to barrio Caño in Guánica, forty miles away,
    because Caño is the only gazetteer name in the sentence. The gazetteer is
    not complete - Caño Martín Peña, Villa Cañona and La Parguera are all
    missing - so a match that is flanked by another capitalised word is treated
    as a fragment of a name nobody here knows, rather than a place.
    """
    words = name.split()
    pattern = r"\s+".join(re.escape(w) for w in words)
    for m in re.finditer(pattern, _strip(original)):
        before = original[: m.start()].rstrip()
        after = original[m.end() :].lstrip()
        if re.search(r"(?:^|\s)[A-ZÁÉÍÓÚÑ][\wáéíóúñü]*$", before):
            return True
        if re.match(r"[A-ZÁÉÍÓÚÑ][\wáéíóúñü]*", after):
            return True
    return False


def _cued(text: str, name: str) -> bool:
    """Whether a place word introduces this name: "barrio Playa", "sector Centro"."""
    for cue in _CUES:
        if re.search(_EDGE + re.escape(cue) + r"\s+(?:de\s+)?" + re.escape(name) + _EDGE_END, text):
            return True
    return False


def resolve(text: str) -> Place | None:
    """The place a question is about, or None when it does not name one.

    None is a real answer and the common one: most questions are island-wide,
    and guessing a place where none was named produces a number about somewhere
    the reader never asked about.
    """
    if not text:
        return None
    try:
        by_name, pattern = _load()
    except Exception:
        return None

    t = _strip(text)
    found = {m.group(0) for m in pattern.finditer(t)}
    if not found:
        return None

    # A barrio named together with its municipality is the clearest case there
    # is, and the only way an ambiguous or ordinary name is ever accepted:
    # "Pueblo, Ponce" names one place where "Pueblo" names seventy-four.
    qualified = [
        p
        for key in found
        for p in by_name[key]
        if p.unit_type != "municipio" and p.parent_name and _strip(p.parent_name) in found
    ]
    if qualified:
        return max(qualified, key=lambda p: len(p.name))

    for key in sorted(found, key=len, reverse=True):
        group = by_name[key]
        if group[0].unit_type == "municipio":
            return group[0]
        if len(group) > 1:
            continue  # several places share this name and nothing says which
        place = group[0]
        if place.common_word and not _cued(t, key):
            continue  # "la costa" is not barrio Costa
        if _part_of_a_longer_name(text, key):
            continue  # "Caño Martín Peña" is not barrio Caño
        return place
    return None


def by_code(unit_code: str) -> Place | None:
    by_name, _ = _load()
    for places in by_name.values():
        for p in places:
            if p.unit_code == unit_code:
                return p
    return None


def municipio(name: str | None) -> Place | None:
    """The municipality of that name."""
    if not name:
        return None
    by_name, _ = _load()
    for p in by_name.get(_strip(name), []):
        if p.unit_type == "municipio":
            return p
    return None


def from_selection(text: str | None) -> Place | None:
    """A place the user picked from the search box rather than typed in a question.

    It arrives the way the box displayed it - "Santurce, San Juan" - so the
    municipality after the comma is what tells the nine places called Buena Vista
    apart. A picked place is not a guess, so the rules that refuse an ambiguous
    or ordinary name in prose do not apply here; only the name has to match.
    """
    if not text:
        return None
    name, _, parent = text.partition(",")
    name, parent = _strip(name.strip()), _strip(parent.strip())
    try:
        by_name, _unused = _load()
    except Exception:
        return None
    group = by_name.get(name, [])
    if parent:
        for p in group:
            if p.parent_name and _strip(p.parent_name) == parent:
                return p
    for p in group:
        if p.unit_type == "municipio":
            return p
    return group[0] if len(group) == 1 else None


def scope_clause(place: Place | str | None, alias: str = "f") -> tuple[str, list[str]]:
    """SQL limiting a feature table to one place, plus its parameters.

    Scoping by code rather than by name is what lets a barrio be a scope: the
    old clause hard-coded unit_type='municipio' because a name was all it had.
    """
    if place is None:
        return "", []
    if isinstance(place, str):  # a municipality name, from an older caller
        resolved = municipio(place)
        if resolved is None:
            return "", []
        place = resolved
    return (
        f" AND EXISTS (SELECT 1 FROM reference_units r WHERE r.unit_code = %s "
        f"AND ST_Intersects(r.geom, {alias}.geom))",
        [place.unit_code],
    )


def bbox(place: Place | None) -> list[float] | None:
    """[west, south, east, north], so the map can fly to it."""
    if place is None:
        return None
    with db.connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT ST_XMin(e), ST_YMin(e), ST_XMax(e), ST_YMax(e) FROM "
            "(SELECT ST_Extent(geom) e FROM reference_units WHERE unit_code = %s) t",
            (place.unit_code,),
        )
        r = cur.fetchone()
    if r and r[0] is not None:
        return [float(r[0]), float(r[1]), float(r[2]), float(r[3])]
    return None
