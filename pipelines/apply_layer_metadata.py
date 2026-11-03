"""Put La Maraña's reconstructed metadata into the database from the repository.

data/layer_metadata.csv is what import_reconstructed_metadata read from their
Metadata Reconstruída workbooks, one row per sheet and layer: description,
agency, purpose, limitations, the original metadata they found, and how sure
they are (Confirmed / Inferred / Reconstructed / Unknown). Keeping it here means
every release applies the same metadata to staging and to production; their
workbooks themselves stay on Drive.

A value is only ever filled in, never blanked: an empty cell leaves what the
layer already has.

To refresh it after they update their workbooks:
    python -m pipelines.import_reconstructed_metadata --src "<their folder>" \\
        --export data/layer_metadata.csv

Run:
    python -m pipelines.apply_layer_metadata            # dry run
    python -m pipelines.apply_layer_metadata --commit
"""

from __future__ import annotations

import argparse
import csv
import os
from pathlib import Path

import psycopg2

SOURCE_FILE = Path("data/layer_metadata.csv")
SOURCE = "La Maraña — Metadata Reconstruída"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true")
    args = ap.parse_args()
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        raise SystemExit("DATABASE_URL not set")
    with SOURCE_FILE.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    conn = psycopg2.connect(dsn)
    cur = conn.cursor()
    # Columns for what their reconstruction provides, on a database that has
    # never had it imported.
    for col in (
        "purpose",
        "limitation",
        "federal_agency",
        "original_metadata",
        "metadata_reference",
        "metadata_source",
    ):
        cur.execute(f"ALTER TABLE layer_registry ADD COLUMN IF NOT EXISTS {col} text")
    updated = missing = 0
    for r in rows:
        cur.execute(
            """
            UPDATE layer_registry SET
              description_es     = COALESCE(NULLIF(%s,''), description_es),
              source_agency      = COALESCE(NULLIF(%s,''), source_agency),
              federal_agency     = COALESCE(NULLIF(%s,''), federal_agency),
              purpose            = COALESCE(NULLIF(%s,''), purpose),
              limitation         = COALESCE(NULLIF(%s,''), limitation),
              original_metadata  = COALESCE(NULLIF(%s,''), original_metadata),
              metadata_reference = COALESCE(NULLIF(%s,''), metadata_reference),
              metadata_status    = COALESCE(NULLIF(%s,''), metadata_status),
              metadata_source    = %s,
              updated_at         = now()
            WHERE id = %s
            """,
            (
                r["description"],
                r["agency"],
                r["federal_agency"],
                r["purpose"],
                r["limitation"],
                r["original_metadata"],
                r["reference"],
                r["confidence"],
                SOURCE,
                r["id"],
            ),
        )
        if cur.rowcount:
            updated += 1
        else:
            missing += 1

    print(f"[metadata] {updated} rows applied from {SOURCE_FILE}")
    if missing:
        print(f"[metadata] {missing} rows name a layer this database does not have")
    if args.commit:
        conn.commit()
        print("[metadata] committed")
    else:
        conn.rollback()
        print("[metadata] dry run — rolled back. Use --commit to write.")


if __name__ == "__main__":
    main()
