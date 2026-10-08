"""English names for the layers, translated from La Maraña's own names.

The app switches between Spanish and English, but their inventory gives each layer
one name - Spanish, or a file name like `aeropuertos_helipuertos_faa_2021`. In
English mode the panel stayed Spanish.

This translates their name, and only their name. It does not describe the layer,
guess at what a code means, or add anything the name does not say. Agency
acronyms, years and place names are kept as they are.

The result goes to a file in the repository, data/layer_names_en.csv, not to the
database. That file is the thing to review: every row shows their name beside
the translation, and every translation is marked as machine-made, so La Maraña
can correct any of them. pipelines/apply_layer_names puts the reviewed file into
the database.

Run:
    python -m pipelines.translate_layer_names          # writes data/layer_names_en.csv
"""

from __future__ import annotations

import csv
import json
import os
from pathlib import Path

import psycopg2

OUT = Path("data/layer_names_en.csv")
BATCH = 40
MODEL = os.environ.get("LLM_MODEL", "gemini-2.5-flash-lite")

PROMPT = """You translate the names of Puerto Rico GIS map layers from Spanish into English.

Rules:
- Translate the name only. Do not describe the layer, explain a code, or add anything the
  name does not say.
- Many names are file names: underscores, abbreviations, prefixes like "g11" or "g23".
  Write them as a readable English name, dropping prefixes like g01/g11/g23 and words
  like "project" or "exportfeatures" that are file-export leftovers.
- Keep agency acronyms (FEMA, FAA, PRASA, AAA, AEE, PREPA, DRNA, CRIM, USGS, EPA, FWS,
  PRIDCO, NOAA, JP), years and place names (Monte Choca, Isabela, Caño Martín Peña) as written.
- Keep Puerto Rican planning terms that have no exact English equivalent and add the
  English in parentheses only if it is a direct translation, e.g. "Comunidades especiales
  (special communities)".
- If a name is already English, return it unchanged.

Return JSON: a list of {"id": ..., "en": ...}, one per input, same ids.

Names:
"""


def translate(batch: list[dict]) -> dict[str, str]:
    from google import genai
    from google.genai import types

    client = genai.Client(
        vertexai=True,
        project=os.environ.get("GCP_PROJECT", "mappa-lamarana-aecc"),
        location=os.environ.get("VERTEX_LOCATION", "us-central1"),
    )
    lines = "\n".join(
        json.dumps({"id": r["id"], "name": r["name_es"]}, ensure_ascii=False) for r in batch
    )
    resp = client.models.generate_content(
        model=MODEL,
        contents=PROMPT + lines,
        config=types.GenerateContentConfig(temperature=0, response_mime_type="application/json"),
    )
    out = {}
    for x in json.loads(resp.text):
        en = (x.get("en") or "").strip()
        if en:
            # One capitalisation for every name: "airports heliports FAA 2021"
            # beside "Land Use Plan 2015" read as two different products.
            out[str(x["id"])] = en[0].upper() + en[1:]
    return out


def main() -> None:
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        raise SystemExit("DATABASE_URL not set")
    with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
        # Reading only. Nothing here writes to the database.
        cur.execute(
            """SELECT id, table_name, name_es FROM layer_registry
               WHERE status IN ('published', 'loaded') AND name_es IS NOT NULL
               ORDER BY status = 'published' DESC, table_name"""
        )
        rows = [{"id": r[0], "table_name": r[1], "name_es": r[2]} for r in cur.fetchall()]

    done: dict[str, str] = {}
    for i in range(0, len(rows), BATCH):
        batch = rows[i : i + BATCH]
        for attempt in range(3):
            try:
                done.update(translate(batch))
                break
            except Exception as exc:  # a malformed reply is retried, then skipped
                if attempt == 2:
                    print(f"  batch {i // BATCH + 1} failed: {str(exc)[:80]}")
        print(f"  {min(i + BATCH, len(rows))} / {len(rows)}", flush=True)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["id", "table_name", "name_es", "name_en", "source"])
        for r in rows:
            en = done.get(str(r["id"]), "")
            w.writerow(
                [
                    r["id"],
                    r["table_name"],
                    r["name_es"],
                    en,
                    "machine translation of La Maraña's name" if en else "",
                ]
            )
    missing = sum(1 for r in rows if str(r["id"]) not in done)
    print(f"\n[names] {len(rows) - missing} of {len(rows)} translated -> {OUT}")
    if missing:
        print(f"[names] {missing} not translated; rerun to fill them")


if __name__ == "__main__":
    main()
