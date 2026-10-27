"""Give every layer an embedding, so questions find layers by meaning.

A layer is described in the same 384-dimension space the questions live in: its
names in both languages, description, category, agency and year, the columns it
has, and what profile_layers found inside it - its main categories and a sample
of its feature names. "Where are the rivers?" then finds the hydrography layer by
the Río Grande de Loíza in it, though its name never says river.

Run after profile_layers, so the content summaries are current:
    python -m pipelines.embed_layers --commit
"""

from __future__ import annotations

import argparse
import os

import psycopg2
from psycopg2.extras import execute_batch

from core import EMBED_DIM
from core import EMBEDDING_MODEL as MODEL


def describe(row: dict) -> str:
    """The text that represents a layer.

    Everything a person might say when looking for it, and only what came from
    La Maraña or from the layer itself. The name is repeated deliberately - it is
    the strongest signal and the one most likely to appear in a question.
    """
    # What a click shows, in La Maraña's words where their dictionary names the
    # field ("Average wind speed in January ... in knots"), else the column name.
    labels = row.get("property_labels") or {}
    seen: list[str] = []
    for c in row.get("tile_properties") or []:
        text = (labels.get(c) or {}).get("en") or c.replace("_", " ")
        if text not in seen:
            seen.append(text)
    columns = " ".join(seen[:12])
    parts = [
        row.get("name_es"),
        row.get("name_es"),
        row.get("name_en"),
        row.get("description_es"),
        row.get("description_en"),
        row.get("purpose"),
        row.get("category"),
        row.get("subcategory"),
        row.get("source_agency"),
        str(row["vintage_year"]) if row.get("vintage_year") else None,
        " ".join(row.get("keywords") or []),
        row.get("content_summary"),
        columns,
    ]
    return " · ".join(p for p in parts if p)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true")
    ap.add_argument("--batch", type=int, default=128)
    args = ap.parse_args()
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        raise SystemExit("DATABASE_URL not set")

    from sentence_transformers import SentenceTransformer

    conn = psycopg2.connect(dsn)
    conn.autocommit = False
    cur = conn.cursor()
    cur.execute("SET statement_timeout='300s'")
    cur.execute(
        f"ALTER TABLE layer_registry ADD COLUMN IF NOT EXISTS embedding vector({EMBED_DIM})"
    )
    cur.execute("ALTER TABLE layer_registry ADD COLUMN IF NOT EXISTS embed_text text")
    conn.commit()

    cur.execute("""
        SELECT id, name_es, name_en, description_es, description_en, purpose, category,
               subcategory, source_agency, vintage_year, keywords, content_summary,
               tile_properties, property_labels
        FROM layer_registry ORDER BY id
    """)
    cols = [d[0] for d in cur.description]
    rows = [dict(zip(cols, r, strict=False)) for r in cur.fetchall()]
    print(f"[embed] {len(rows)} layers")

    model = SentenceTransformer(MODEL)
    texts = [describe(r) for r in rows]
    vecs = model.encode(
        texts, normalize_embeddings=True, batch_size=args.batch, show_progress_bar=False
    )

    payload = [
        ("[" + ",".join(f"{x:.6f}" for x in v) + "]", t, r["id"])
        for r, t, v in zip(rows, texts, vecs, strict=True)
    ]
    execute_batch(
        cur,
        "UPDATE layer_registry SET embedding=%s::vector, embed_text=%s WHERE id=%s",
        payload,
        page_size=100,
    )

    # No index: at ~700 rows an exact scan is fast and beats an approximate one.
    print(f"[embed] embedded {len(payload)} layers")
    if args.commit:
        conn.commit()
        print("[embed] committed")
    else:
        conn.rollback()
        print("[embed] dry run — rolled back. Use --commit to write.")


if __name__ == "__main__":
    main()
