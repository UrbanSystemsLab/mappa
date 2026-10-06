"""Decide, from each layer's own data, what the map shows when it is drawn.

Every layer was drawn in one flat colour, and 72 of the 82 on the map sent no
information at all when clicked. The land use plan holds seventeen kinds of land
- urban, protected agricultural, protected ecological, water - and all of it was
the same green. The soil layer has 30,277 areas with fifty facts each and showed
an empty popup. The data was there; the map was not asking for it.

This reads each of the ~600 layers that have data and settles two things:

  what a click shows   the columns that actually hold something. Geometry and
                       bookkeeping columns are left out, as are columns that are
                       empty, or always the same value, or always -9999 - GIS
                       data's code for "no value".

  what colours mean    if the layer has a column that sorts its features into a
                       handful of kinds, the features are coloured by it and the
                       legend shows their values. Their words, never ours.

It only decides from what is in the data. Column names are shown as they are,
because readable names would be words we chose; those will come from La
Maraña's data dictionaries.

Run:
    python -m pipelines.profile_layers            # dry run
    python -m pipelines.profile_layers --commit
    python -m pipelines.profile_layers --table layer_soil_mu_pr
"""

from __future__ import annotations

import argparse
import json
import os
import re

import psycopg2

# Columns that describe the file, not the place.
BOOKKEEPING = re.compile(
    r"^(geom|geom_simple|geom_coarse|wkb_geometry|the_geom|objectid(_\d+)?|ogc_fid|fid|"
    r"fid_.*|gid|id|globalid|shape_leng|shape_length|shape_area|shape_le_\d+|shape_ar_\d+|"
    r"st_area.*|st_length.*|area|perimeter|len|length|created_.*|last_edited_.*|"
    r"editor|creator|lkey|mukey|cntyidfp|countyfp|spatialver|"
    # Parcel-data and editing bookkeeping: record IDs, file paths, survey book
    # and page, coordinates repeated as columns, the initials of whoever edited.
    r"ll_.*|path|census_.*|qoz.*|geoid.*|alt_parc.*|parcelnu_\d|oldpid|book|page|"
    r"scity_orig|address_so|xcoord|ycoord|updatedby.*|recrdarean|.*gisacre|.*gissqft|"
    # Mapping-software internals: the PREPA network carries G/Technology's own
    # record keys and symbol rotations (g3e_id, g3e_fid, gmrotation), which mean
    # nothing to anyone reading the map.
    r"g3e_.*|gm.*rotation|.*rotation|symbol.*|ltt_.*|enabled|shape_.*|st_.*|ruleid|override)$",
    re.I,
)
# A place name sorts features by where they are, not by what they are.
# Colouring hospitals by town tells you nothing the map does not already show.
NOT_A_KIND = re.compile(
    r"^(municipio|muni|municipality|mun|county|cnty.*|abrev|barrio|region|nombre|name|"
    r"direccion|address|dir|calle|telefono|phone|tel|url|web|email|fecha.*|date.*|"
    # Survey and file references: FEMA's flood layer has a vertical-datum column
    # with two values, and it was chosen to colour flood zones by.
    r"v_datum|datum|crs|proj.*|source|fuente|version|ver|"
    # Statistical and geocoding references, and citations. The cadastral maps
    # were coloured by census block number and by a geocoder's working note
    # ("county,census_places"); the habitat layers by the journal they cite.
    r"census.*|cbsa.*|geoid.*|tract.*|block.*|fips.*|address_.*|areasymbol|publicat.*|cita.*|"
    # Parcel-data bookkeeping and addresses: the cadastral maps were coloured by a
    # field-change log ("parcelnumb | geometry | address") and by street address.
    r"city|scity.*|county|state\d*|zip.*|szip.*|ll_.*|path|title.*|urbaniz.*|sadd.*|sunit)$",
    re.I,
)
# Column names that say they hold a kind of thing. Asked first, because the
# kind that matters is often a short code - flood zone "AE" - beside a longer
# column that is merely technical.
KIND_WORDS = re.compile(
    r"(zon|tip|type|clas|cat|desc|uso|use|kind|grup|group|nivel|level|riesg|risk)", re.I
)
NO_VALUE = {"-9999", "-9999.0", "-99999", "-999", "-999.0", "", "\x08"}
# Fields about private people. The 78 cadastral maps carry each parcel's owner,
# mailing address, sale price and tax amount; on a public map a click would show
# a resident's name and where their post goes. These are never shown on click.
# An "owner" column is still allowed as a colour when it has only a handful of
# values - that is an organisation (PRASA, PRV, GOV), not a person.
PERSONAL = re.compile(
    r"^(owner|owner_.*|propietario|dueno|dueño|mailadd|mail.*|buyer.*|seller.*|saleprice|"
    r"saledate|taxamt|taxable|exemp|exon|deednum|address|address2|direccion.*|direccio_\d|"
    r"original_a|address_or|lat|lon)$",
    re.I,
)

MAX_SHOWN = 6  # every property is repeated per feature per tile
MAX_KINDS = 20  # beyond this a legend stops being readable
SAMPLE = 5000

# A qualitative palette: distinguishable from one another, readable on a light
# basemap, and none of them the blue the map uses for water.
PALETTE = [
    "#1b9e77",
    "#d95f02",
    "#7570b3",
    "#e7298a",
    "#66a61e",
    "#e6ab02",
    "#a6761d",
    "#1f78b4",
    "#b2df8a",
    "#fb9a99",
    "#cab2d6",
    "#ff7f00",
    "#6a3d9a",
    "#b15928",
    "#8dd3c7",
    "#bebada",
    "#fb8072",
    "#80b1d3",
    "#fdb462",
    "#b3de69",
]


# Water is blue whatever else is going on. Handing out colours by frequency made
# "Agua" orange on the land use plan, which reads as anything but water.
WATER = re.compile(r"^(agua|aguas|water|cuerpos? de agua|lago|lagos|rio|ríos?|mar)$", re.I)


def colour_for(value: str, i: int) -> str:
    return "#4a90d9" if WATER.match(value.strip()) else PALETTE[i % len(PALETTE)]


def empty(v) -> bool:
    return v is None or str(v).strip() in NO_VALUE


def columns(cur, table: str) -> list[tuple[str, str]]:
    cur.execute(
        """SELECT column_name, data_type FROM information_schema.columns
           WHERE table_schema = 'public' AND table_name = %s ORDER BY ordinal_position""",
        (table,),
    )
    return [(c, t) for c, t in cur.fetchall() if not BOOKKEEPING.match(c) and t != "USER-DEFINED"]


def profile(cur, table: str, cols: list[tuple[str, str]]) -> list[dict]:
    """Fill, variety and length of each column, from a sample of rows."""
    if not cols:
        return []
    names = ", ".join(f'"{c}"' for c, _ in cols)
    cur.execute(f'SELECT {names} FROM "{table}" LIMIT {SAMPLE}')
    rows = cur.fetchall()
    if not rows:
        return []
    out = []
    for i, (name, dtype) in enumerate(cols):
        values = [r[i] for r in rows if not empty(r[i])]
        distinct = {str(v).strip() for v in values}
        out.append(
            {
                "name": name,
                "text": dtype in ("text", "character varying", "character"),
                "fill": len(values) / len(rows),
                "distinct": len(distinct),
                "avg_len": (sum(len(str(v)) for v in values) / len(values)) if values else 0,
            }
        )
    return out


def kinds(cur, table: str, column: str, features: int) -> list[tuple[str, int]] | None:
    """Every value of a candidate column across the whole layer, or None if it
    is not a column that sorts features into a few kinds."""
    cur.execute(
        f'SELECT trim("{column}"::text), count(*) FROM "{table}" '
        f'WHERE "{column}" IS NOT NULL GROUP BY 1 ORDER BY 2 DESC LIMIT {MAX_KINDS + 1}'
    )
    found = [(v, n) for v, n in cur.fetchall() if not empty(v)]
    if not (2 <= len(found) <= MAX_KINDS):
        return None
    # Numbers are identifiers or measurements, not kinds: tract 72003430501 and
    # tract 72003430200 are two places, not two categories of place.
    if sum(1 for v, _ in found if re.fullmatch(r"[\d.\-\s]+", v)) > len(found) // 2:
        return None
    # A column with a different value for nearly every feature is a name or an
    # ID, not a kind - even when the layer is small enough to pass the count.
    if len(found) > max(features // 2, 2):
        return None
    return found


def decide(cur, table: str, features: int) -> tuple[list[str], dict | None]:
    cols = columns(cur, table)
    prof = profile(cur, table, cols)
    useful = [p for p in prof if p["fill"] >= 0.2 and (p["distinct"] > 1 or len(prof) == 1)]

    by = None
    candidates = sorted(
        (
            p
            for p in useful
            if p["text"]
            and p["fill"] >= 0.5
            and 2 <= p["distinct"] <= MAX_KINDS
            and not NOT_A_KIND.match(p["name"])
            # Nothing about private people is a colour - not even where their
            # post goes, which on the cadastral maps would mark absentee owners.
            # A plain owner column with a few values is an organisation and stays.
            and (not PERSONAL.match(p["name"]) or p["name"].lower() == "owner")
        ),
        # Prefer the descriptive column over the code beside it: land use has
        # both CLASIPUT ("SREP-E") and DESCRIPPUT ("Suelo Rústico Especialmente
        # Protegido Ecológico") with the same seventeen values.
        key=lambda p: (not KIND_WORDS.search(p["name"]), -p["avg_len"], p["distinct"]),
    )
    for c in candidates:
        found = kinds(cur, table, c["name"], features)
        if found:
            by = {
                "by": c["name"],
                "categories": [
                    {"value": v, "color": colour_for(v, i), "count": n}
                    for i, (v, n) in enumerate(found)
                ],
            }
            break

    # What a click shows: the colouring column first, then the most telling of
    # the rest. Decided afresh on every run. It used to keep whatever the
    # registry already listed, which after one run meant its own earlier
    # choices - so a column it had wrongly picked could never be dropped again.
    shown: list[str] = [by["by"]] if by else []
    # Words before numbers, and descriptive text before short codes: the soil
    # layer's name ("Humatas clay, 20 to 40 percent slopes") ahead of its map
    # symbol ("HmF").
    for p in sorted(useful, key=lambda p: (not p["text"], -min(p["avg_len"], 60), -p["fill"])):
        if len(shown) >= MAX_SHOWN:
            break
        if PERSONAL.match(p["name"]) and not (
            p["name"].lower() == "owner" and p["distinct"] <= MAX_KINDS
        ):
            continue  # a person's details, not an organisation's
        if p["name"] not in shown:
            shown.append(p["name"])
    return shown, by


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true")
    ap.add_argument("--table")
    args = ap.parse_args()
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        raise SystemExit("DATABASE_URL not set")

    conn = psycopg2.connect(dsn)
    cur = conn.cursor()
    cur.execute("SET statement_timeout='120s'")
    where = "AND table_name = %s" if args.table else ""
    cur.execute(
        f"""SELECT id, table_name, coalesce(feature_count, 0), coalesce(tile_properties, '{{}}'),
                   coalesce(style, '{{}}'::jsonb)
            FROM layer_registry
            WHERE status IN ('published', 'loaded') AND table_name IS NOT NULL {where}
            ORDER BY table_name""",
        (args.table,) if args.table else (),
    )
    layers = cur.fetchall()

    coloured = clickable = nothing = failed = 0
    for rid, table, features, _old, style in layers:
        try:
            shown, by = decide(cur, table, features)
        except Exception as exc:
            conn.rollback()
            cur.execute("SET statement_timeout='120s'")
            failed += 1
            print(f"    could not read {table}: {str(exc).splitlines()[0][:80]}")
            continue
        style = dict(style or {})
        style.pop("by", None)
        style.pop("categories", None)
        # Colouring by category was tried on 3 Oct and made the map harder to
        # read. The choice is still worked out and reported, but not written.
        if by:
            coloured += 1
        if shown:
            clickable += 1
        else:
            nothing += 1
        cur.execute(
            "UPDATE layer_registry SET tile_properties = %s, style = %s WHERE id = %s",
            (shown, json.dumps(style), rid),
        )
        if args.table:
            print(f"  {table}\n    click shows: {shown}")
            if by:
                print(f"    coloured by: {by['by']}")
                for c in by["categories"]:
                    print(f"      {c['count']:>7,}  {c['value']}")

    print(f"\n[profile] {len(layers)} layers with data")
    print(f"    {clickable:>4}  now show their information when clicked")
    print(f"    {coloured:>4}  could be coloured by category (not applied)")
    print(f"    {nothing:>4}  hold nothing beyond their shape")
    if failed:
        print(f"    {failed:>4}  could not be read")

    if args.commit:
        conn.commit()
        print("\n[profile] committed")
    else:
        conn.rollback()
        print("\n[profile] dry run — rolled back. Use --commit to write.")


if __name__ == "__main__":
    main()
