"""Set the featured layers from La Maraña's prioritization matrix.

On 28 July 2026 Ailani sent "the short list of the layers we consider reliable
enough to prioritize first based on their publication date and the metadata
available" - the Data Quality Prioritization Matrix. It sat unused for ten weeks
while the map was chosen by us. This applies it.

The matrix is transcribed into data/lamarana_priority_layers.csv with one column
added: which of our tables each row is. Fourteen of their sixteen names match a
table exactly. The other two were mapped by hand:

  PACAT2018_terrestres_marinas_amortiguamento  one name on their sheet, three
                                               tables here - terrestrial, marine
                                               and buffer zones were loaded
                                               separately
  corredor_agricola_del_sur                    loaded under the name of the
                                               export that produced it

Featured is a flag, not a filter. Their layers lead the panel; the others stay
on the map underneath, because an answer about schools has to be able to show
schools whether or not schools made their list.

Run:
    python -m pipelines.apply_priority_list            # dry run
    python -m pipelines.apply_priority_list --commit
"""

from __future__ import annotations

import argparse
import csv
import os
from pathlib import Path

import psycopg2

SOURCE = Path("data/lamarana_priority_layers.csv")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true")
    args = ap.parse_args()
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        raise SystemExit("DATABASE_URL not set")

    with SOURCE.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    conn = psycopg2.connect(dsn)
    cur = conn.cursor()

    # Their list replaces whatever was featured before - it is the whole answer,
    # not an addition to one.
    cur.execute("UPDATE layer_registry SET featured = false, featured_note = NULL")

    featured, published, missing = [], [], []
    for row in rows:
        for table in row["tables"].split(";"):
            cur.execute(
                "SELECT id, status FROM layer_registry WHERE table_name = %s "
                "AND status IN ('published', 'loaded')",
                (table,),
            )
            hit = cur.fetchone()
            if not hit:
                missing.append((row["their_name"], table))
                continue
            rid, status = hit
            # A layer they prioritised has to be drawable, or featuring it
            # puts a toggle on the panel that does nothing.
            cur.execute(
                "UPDATE layer_registry SET featured = true, featured_note = %s, "
                "status = 'published' WHERE id = %s",
                (row["notes"] or None, rid),
            )
            featured.append((row["their_name"], table))
            if status != "published":
                published.append(table)

    print(f"[priority] {len(rows)} rows on their matrix -> {len(featured)} layers featured")
    for name, table in featured:
        print(f"    {name[:46]:48} {table}")
    print(f"\n[priority] {len(published)} were queryable but not on the map, now published:")
    for table in published:
        print(f"    {table}")
    if missing:
        print(f"\n[priority] {len(missing)} could not be found - check the mapping:")
        for name, table in missing:
            print(f"    {name:48} -> {table}")

    if args.commit:
        conn.commit()
        print("\n[priority] committed")
    else:
        conn.rollback()
        print("\n[priority] dry run — rolled back. Use --commit to write.")


if __name__ == "__main__":
    main()
