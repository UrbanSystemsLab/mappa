"""Populate reference_units with every named place, not just municipalities.

reference_units held 78 municipios and nothing else, and every spatial function
took a place *name* and looked one up. That is why there was no barrio, no
community, and no way to ask about anywhere smaller than a municipality - a
question about Villa Cañona or Caño Martín Peña had nowhere to land.

What goes in is a judgement, not everything available. A barrio and a comunidad
especial are places people name. A census block is "Block Group 2" and a tract is
"Census Tract 9905.01" - those are statistical units referenced by number, and
putting them in a gazetteer people search by name would bury the real places.

Names repeat across the island - most municipalities have a barrio called Pueblo -
so each row also carries the municipality it sits in, and resolution prefers an
exact qualified match before a bare one.

Many are also ordinary Spanish words. There is a barrio called Playa, one called
Pueblo and one called Llano, and a question about "la playa" must not be scoped
to a two-square-kilometre barrio. Which names are ordinary words is measured
rather than guessed: a sample of the corpus is tokenised, and a name that turns
up lowercase in a fair share of chunks is marked so resolution will only accept
it when something else in the sentence qualifies it.

Run:
    python -m pipelines.build_gazetteer --commit
"""

from __future__ import annotations

import argparse
import collections
import os
import re
import unicodedata

import psycopg2

# Each source: the layer, the column holding the name, and the column holding the
# municipality it belongs to.
SOURCES = [
    {
        "unit_type": "barrio",
        "table": "layer_barrios_2015_corrected_16_nov17",
        "name": "barrio",
        "parent": "municipio",
    },
    {
        "unit_type": "comunidad",
        "table": "layer_asentamientos_delimitacion_comunidades_especiales_2006",
        "name": "nombre",
        "parent": "municipio",
    },
]


# A name appearing lowercase in this share of sampled chunks is an ordinary word.
# Set above every municipality name - OCR lowercases a few of those - and below
# Marina, Arenas and Llano, which are the first genuine nouns.
COMMON_WORD_SHARE = 0.0015
WORD = re.compile(r"\b[a-záéíóúñü][a-záéíóúñü]{2,}\b")


def _strip(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in text if not unicodedata.combining(c))


def attach_parents(cur) -> None:
    """Set each place's municipality from where it is, not from what it says.

    The comunidades especiales layer carries a municipality column, and in 139 of
    its 713 rows that column is corrupt: Añasco arrives as Aaasco, Aeasco, AOasco
    and four other spellings, each row's accented character replaced by a
    different one. Canóvanas and Cataño are mangled the same way.

    So the column is not trusted for anything. The 78 municipality polygons are
    authoritative and intact, and a place's municipality is which one it sits in -
    a fact the geometry already holds. The text column is kept only where no
    polygon contains the place, which is nowhere at present but would be the case
    for anything offshore.
    """
    cur.execute("""
        UPDATE reference_units child
        SET parent_name = m.name
        FROM reference_units m
        WHERE m.unit_type = 'municipio'
          AND child.unit_type <> 'municipio'
          -- A point inside the shape, so a barrio touching a boundary is not
          -- claimed by its neighbour.
          AND ST_Intersects(m.geom, ST_PointOnSurface(child.geom))
    """)
    print(f"[gazetteer] {cur.rowcount:>6,} places placed in their municipality by geometry")

    cur.execute("""
        SELECT count(*) FROM reference_units child
        WHERE child.unit_type <> 'municipio' AND NOT EXISTS (
            SELECT 1 FROM reference_units m WHERE m.unit_type = 'municipio'
              AND unaccent_fallback(lower(m.name)) = unaccent_fallback(lower(child.parent_name))
        )
    """)
    stranded = cur.fetchone()[0]
    if stranded:
        print(f"[gazetteer] {stranded} places still have no municipality — check their geometry")


def mark_common_words(cur) -> None:
    """Flag the place names that are also ordinary words.

    Measured from the corpus rather than hand-listed, because a hand-list is a
    guess that goes stale. Only the lowercase form counts: "Santurce" never
    appears as a common noun and scores zero, while "playa" is in a hundred
    chunks.
    """
    cur.execute("ALTER TABLE reference_units ADD COLUMN IF NOT EXISTS common_word boolean")
    cur.execute("UPDATE reference_units SET common_word = false")

    # A sample, not the whole corpus: 110,000 chunks to settle a question about
    # 600 words is work nobody needs doing.
    cur.execute("SELECT text FROM document_chunks TABLESAMPLE SYSTEM (12) LIMIT 20000")
    chunks = [r[0] for r in cur.fetchall() if r[0]]
    if not chunks:
        print("[gazetteer] no corpus to measure against — common words left unmarked")
        return

    seen: collections.Counter[str] = collections.Counter()
    for text in chunks:
        seen.update({_strip(w) for w in WORD.findall(text)})  # distinct chunks, not hits
    floor = max(int(len(chunks) * COMMON_WORD_SHARE), 10)

    # Municipalities are exempt. Arroyo is a municipality and also a word for a
    # stream; the 78 are the authoritative names and are never in doubt.
    cur.execute(
        "SELECT DISTINCT name FROM reference_units "
        "WHERE unit_type <> 'municipio' AND name NOT LIKE '%% %%'"
    )
    common = [n for (n,) in cur.fetchall() if seen[_strip(n)] >= floor]
    if common:
        cur.execute(
            "UPDATE reference_units SET common_word = true "
            "WHERE unit_type <> 'municipio' AND name = ANY(%s)",
            (common,),
        )
    print(
        f"[gazetteer] {len(common)} names are also ordinary words "
        f"(>= {floor} of {len(chunks):,} sampled chunks): "
        + ", ".join(sorted(common)[:12])
        + (" ..." if len(common) > 12 else "")
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true")
    args = ap.parse_args()
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        raise SystemExit("DATABASE_URL not set")

    conn = psycopg2.connect(dsn)
    cur = conn.cursor()
    cur.execute("SET statement_timeout='300s'")

    # A place needs to know which municipality it is in, so a question can be
    # scoped to "Pueblo, Ponce" rather than the eleven barrios called Pueblo.
    cur.execute("ALTER TABLE reference_units ADD COLUMN IF NOT EXISTS parent_name text")
    cur.execute("ALTER TABLE reference_units ADD COLUMN IF NOT EXISTS source_table text")
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_reference_units_name ON reference_units (lower(name))"
    )

    for src in SOURCES:
        cur.execute(
            """SELECT 1 FROM information_schema.tables
               WHERE table_schema='public' AND table_name=%s""",
            (src["table"],),
        )
        if not cur.fetchone():
            print(f"[gazetteer] {src['unit_type']}: {src['table']} not loaded — skipped")
            continue

        # Replace rather than append, so a rerun after a layer reload does not
        # leave two copies of every barrio.
        cur.execute("DELETE FROM reference_units WHERE unit_type=%s", (src["unit_type"],))
        cur.execute(
            f"""
            INSERT INTO reference_units (unit_type, unit_code, name, parent_name,
                                         source_table, geom)
            SELECT unit_type, unit_type || '-' || row_number() OVER (ORDER BY name, parent),
                   name, parent, source, geom
            FROM (
                SELECT %s AS unit_type,
                       trim("{src["name"]}") AS name,
                       trim("{src["parent"]}") AS parent,
                       %s AS source,
                       -- One row per named place: a barrio split across several
                       -- polygons is one place, not several.
                       ST_Multi(ST_Union(ST_Force2D(geom))) AS geom
                FROM "{src["table"]}"
                WHERE geom IS NOT NULL AND "{src["name"]}" IS NOT NULL
                  AND trim("{src["name"]}") <> ''
                GROUP BY 1, 2, 3, 4
            ) grouped
            """,
            (src["unit_type"], src["table"]),
        )
        print(f"[gazetteer] {src['unit_type']:12} {cur.rowcount:>6,} places")

    attach_parents(cur)
    mark_common_words(cur)

    cur.execute("SELECT unit_type, count(*) FROM reference_units GROUP BY 1 ORDER BY 2 DESC")
    print("\n[gazetteer] reference_units now holds:")
    total = 0
    for unit, n in cur.fetchall():
        print(f"    {n:>6,}  {unit}")
        total += n
    print(f"    {total:>6,}  total")

    if args.commit:
        conn.commit()
        print("\n[gazetteer] committed")
    else:
        conn.rollback()
        print("\n[gazetteer] dry run — rolled back. Use --commit to write.")


if __name__ == "__main__":
    main()
