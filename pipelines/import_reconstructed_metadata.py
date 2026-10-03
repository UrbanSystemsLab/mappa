"""Import the metadata La Maraña reconstructed for their GIS layers.

Most of their 649 layers arrived with little more than a name. Over several
months their team went through the attribute tables looking for agency names and
references that would say where each layer came from, and wrote the result up one
workbook per theme. Ailani described the method in July; the files have been in
the Drive since August.

Nothing had read them. The product was inferring confidence from how full a row
was, while they were stating it explicitly.

Two formats, because the work happened in two passes:

  Vertical   (*_Reconstructed_Metadata.xlsm) - one tab per layer, fields down
             column A, with a confidence and a source beside each value. This is
             the format the email thread is about.
  Flat       (Metadata_excel.xlsx) - one tab per layer, fields down column A,
             value in column B. The earlier pass.

Their confidence vocabulary - Confirmed / Inferred / Reconstructed / Unknown - is
already what layer_registry.metadata_status uses, so it maps across directly
rather than being translated.

Run:
    python -m pipelines.import_reconstructed_metadata            # dry run
    python -m pipelines.import_reconstructed_metadata --commit
"""

from __future__ import annotations

import argparse
import os
import re
import unicodedata
from pathlib import Path

import openpyxl
import psycopg2

SRC = Path("data/raw/metadata")
SOURCE = "La Maraña — Metadata Reconstruída"

# Tabs that describe the workbook rather than a layer.
NOT_A_LAYER = {"confidence guide", "guia", "guía", "index", "readme"}

# Their field labels -> our columns. Both passes used different wording for the
# same thing, so both spellings map to one place.
FIELDS = {
    "suggested title": "title",
    "name": "title",
    "description": "description",
    "responsible puerto rico agency": "agency",
    "source agency": "agency",
    "federal agency / authority": "federal_agency",
    "publication date": "published",
    "update date": "revised",
    "geographic coverage": "coverage",
    "spatial coverage": "coverage",
    "coordinate reference system (crs)": "crs",
    "crs": "crs",
    "purpose": "purpose",
    "important limitation": "limitation",
    "usage restrictions/license": "limitation",
    "metadata status": "status_text",
    "original metadata": "original_metadata",
    "primary reference": "reference",
    "source": "reference",
    "geometry type": "geometry",
    "data type": "data_type",
    "dataset name": "dataset_name",
}


# Their four-level vocabulary, which layer_registry already speaks.
def confidence(*texts: str) -> str | None:
    blob = " ".join(t for t in texts if t).lower()
    if not blob:
        return None
    if "confirmed" in blob or "confirmado" in blob:
        return "confirmed"
    if "reconstructed" in blob or "reconstru" in blob:
        return "reconstructed"
    if "inferred" in blob or "inferido" in blob:
        return "inferred"
    if "unknown" in blob or "not identified" in blob:
        return "unknown"
    return None


def norm(text: str) -> str:
    t = unicodedata.normalize("NFKD", (text or "").lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "", t)


def read_tab(ws) -> dict[str, str]:
    """One layer's metadata from one tab.

    Both formats put the field name in column A. The vertical format adds a
    confidence in column C and a source in column D; the flat one does not, so
    the confidence is read from the value itself where it says so.
    """
    out: dict[str, str] = {}
    conf_bits: list[str] = []
    for row in ws.iter_rows(values_only=True):
        if not row or row[0] is None:
            continue
        label = norm(str(row[0]))
        key = next((v for k, v in FIELDS.items() if norm(k) == label), None)
        if not key:
            continue
        value = str(row[1]).strip() if len(row) > 1 and row[1] is not None else ""
        if value and value.lower() not in {"none", "not provided", "n/a"}:
            out.setdefault(key, value)
        # Column C carries their confidence for this particular field.
        if len(row) > 2 and row[2]:
            conf_bits.append(str(row[2]))
        # Column D is where they found it.
        if len(row) > 3 and row[3] and "reference" not in out:
            out.setdefault("reference", str(row[3]).strip())
    c = confidence(*conf_bits, out.get("status_text", ""))
    if c:
        out["confidence"] = c
    return out


def match(cur, dataset: str, tab: str) -> list[str]:
    """Find the registry rows this metadata describes.

    Matched on the layer's own name, not on anything we invented. A tab that
    matches nothing is reported rather than forced onto a near neighbour - their
    sheet has genuine duplicates and a wrong attachment would be recorded as
    provenance.
    """
    for candidate in (dataset, tab):
        if not candidate:
            continue
        key = norm(candidate)
        # Three ways in, because a layer may be published (has a table),
        # loaded, or still only catalogued - and the metadata is just as useful
        # on a row whose data has not arrived yet.
        cur.execute(
            """
            SELECT id FROM layer_registry
            WHERE regexp_replace(lower(translate(coalesce(table_name,''),
                      'áéíóúñü','aeiounu')), '[^a-z0-9]+', '', 'g') IN (%s, %s)
               OR regexp_replace(lower(translate(coalesce(name_es,''),
                      'áéíóúñü','aeiounu')), '[^a-z0-9]+', '', 'g') = %s
               OR gis_id IN (
                    SELECT gis_id FROM layer_inventory
                    WHERE regexp_replace(lower(translate(coalesce(layer_name,''),
                              'áéíóúñü','aeiounu')), '[^a-z0-9]+', '', 'g') = %s)
        """,
            (key, "layer" + key, key, key),
        )
        hits = [r[0] for r in cur.fetchall()]
        if hits:
            return hits
    return []


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true")
    args = ap.parse_args()
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        raise SystemExit("DATABASE_URL not set")

    conn = psycopg2.connect(dsn)
    cur = conn.cursor()
    cur.execute("SET statement_timeout='120s'")
    # Fields their reconstruction provides that the registry had nowhere to put.
    for col in (
        "purpose text",
        "limitation text",
        "federal_agency text",
        "original_metadata text",
        "metadata_reference text",
        "metadata_source text",
    ):
        cur.execute(f"ALTER TABLE layer_registry ADD COLUMN IF NOT EXISTS {col}")
    conn.commit()

    applied, unmatched, tabs = 0, [], 0
    for book in sorted(SRC.glob("*.xls[xm]")):
        wb = openpyxl.load_workbook(book, data_only=True)
        print(f"\n[meta] {book.name}")
        for ws in wb.worksheets:
            if ws.title.strip().lower() in NOT_A_LAYER:
                continue
            tabs += 1
            m = read_tab(ws)
            if not m:
                continue
            ids = match(cur, m.get("dataset_name", ""), ws.title)
            if not ids:
                unmatched.append((book.name, ws.title, m.get("title", "")[:40]))
                continue
            for lid in ids:
                cur.execute(
                    """
                    UPDATE layer_registry SET
                      description_es   = COALESCE(NULLIF(%s,''), description_es),
                      source_agency    = COALESCE(NULLIF(%s,''), source_agency),
                      federal_agency   = COALESCE(NULLIF(%s,''), federal_agency),
                      purpose          = COALESCE(NULLIF(%s,''), purpose),
                      limitation       = COALESCE(NULLIF(%s,''), limitation),
                      original_metadata= COALESCE(NULLIF(%s,''), original_metadata),
                      metadata_reference = COALESCE(NULLIF(%s,''), metadata_reference),
                      metadata_status  = COALESCE(%s, metadata_status),
                      metadata_source  = %s,
                      updated_at       = now()
                    WHERE id = %s
                """,
                    (
                        m.get("description", ""),
                        m.get("agency", ""),
                        m.get("federal_agency", ""),
                        m.get("purpose", ""),
                        m.get("limitation", ""),
                        m.get("original_metadata", ""),
                        m.get("reference", ""),
                        m.get("confidence"),
                        SOURCE,
                        lid,
                    ),
                )
                applied += cur.rowcount
            print(f"   {ws.title[:34]:36} -> {', '.join(ids)[:44]}")
        wb.close()

    print(f"\n[meta] {tabs} layer tabs read, {applied} registry rows updated")
    if unmatched:
        print(f"[meta] {len(unmatched)} tabs matched no layer:")
        for b, t, title in unmatched:
            print(f"   {b[:30]:32} {t[:26]:28} {title}")

    if args.commit:
        conn.commit()
        print("[meta] committed")
    else:
        conn.rollback()
        print("[meta] dry run — rolled back. Use --commit to write.")


if __name__ == "__main__":
    main()
