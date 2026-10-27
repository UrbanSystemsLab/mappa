"""La Maraña's data dictionaries: what each field of a layer means, and whether
they want it shown.

Two files, both reviewed by hand:

  data/layer_dictionaries.csv        their sheets as they wrote them - one row per
                                     field: description, Include (1) or Exclude
                                     (0), and their reason where they gave one.
  data/layer_dictionary_tables.csv   which of our tables each sheet describes.
                                     Sheets were matched by the columns the table
                                     actually has, then checked by eye; a sheet
                                     can describe several copies of one dataset.

A field cell sometimes names more than one column ("LEVEL / LEVEL_") and
shapefiles cut column names to ten characters, so a field is matched to a
column on either. Fields with no column in the table are left out, never
guessed.
"""

from __future__ import annotations

import csv
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

FIELDS = Path("data/layer_dictionaries.csv")
TABLES = Path("data/layer_dictionary_tables.csv")

# Their dictionaries for these show every included field: monthly series that
# only make sense whole. Everywhere else they asked for ten at most.
NO_LIMIT = re.compile(r"Topography|Wind|Temperature", re.I)
LIMIT = 10

# A field their dictionary itself describes as a person's or an owner's name is
# never shown, even where they marked it Include: the farms layer's "nombre" is
# "Property owner name". Same rule as profile_layers' PERSONAL columns.
PRIVATE = re.compile(
    r"\b(owner|propietari\w*|due[ñn]o|individual|person(al)?|resident|"
    r"technical personnel)\b.*\b(name|nombre|identifier)\b|"
    r"\b(name|nombre)\b.*\b(owner|propietari\w*|due[ñn]o|individual|person)\b|"
    # Where a private parcel's taxpayer gets their post. A school's or a
    # shelter's address is public and stays.
    r"\btaxpayer\b|\bproperty address\b",
    re.I,
)


@dataclass(frozen=True)
class Field:
    column: str
    description: str
    include: bool | None  # None where they left the flag blank
    reason: str

    @property
    def shown(self) -> bool:
        return bool(self.include) and not PRIVATE.search(self.description)


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower().strip()
    return re.sub(r"[^a-z0-9]+", "_", s).strip("_")


def _names(field: str) -> list[str]:
    return [norm(p) for p in re.split(r"\s*/\s*", field) if p.strip()]


def sheets_by_table() -> dict[str, tuple[str, str]]:
    with TABLES.open(encoding="utf-8") as f:
        return {r["table_name"]: (r["dictionary"], r["sheet"]) for r in csv.DictReader(f)}


def rows_by_sheet() -> dict[tuple[str, str], list[dict]]:
    out: dict[tuple[str, str], list[dict]] = {}
    with FIELDS.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            out.setdefault((r["dictionary"], r["sheet"].strip()), []).append(r)
    return out


def resolve(rows: list[dict], columns: list[str]) -> list[Field]:
    """Their fields, in their order, as the table's real column names."""
    by_norm = {norm(c): c for c in columns}
    out: list[Field] = []
    seen: set[str] = set()
    for r in rows:
        desc = " ".join(r["description"].split())
        flag = r["include"].strip()
        for name in _names(r["field"]):
            col = by_norm.get(name) or (by_norm.get(name[:10]) if len(name) > 10 else None)
            if not col or col in seen:
                continue
            seen.add(col)
            out.append(Field(col, desc, {"1": True, "0": False}.get(flag), r["reason"].strip()))
    return out


def limit_for(dictionary: str) -> int | None:
    return None if NO_LIMIT.search(dictionary) else LIMIT
