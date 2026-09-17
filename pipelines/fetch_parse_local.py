"""Download planning PDFs from the manifest straight to a local corpus JSON.

A gcloud-free path: fetches each PDF over HTTP, extracts text with PyMuPDF, and
writes documents shaped like data/documents.json so pipelines/ingest_documents.py
can chunk + embed them unchanged. Metadata (title/jurisdiction/type/year/url)
comes straight from data/planning_manifest.csv, so provenance is exact.

Run:
    python -m pipelines.fetch_parse_local --tipo "Plan de Recuperación" --out data/corpus_batch.json
    python -m pipelines.fetch_parse_local --ids DOC-037,DOC-038 --out data/corpus_batch.json
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import ssl
import urllib.request
from pathlib import Path

import fitz  # PyMuPDF

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "data" / "planning_manifest.csv"
RAW_DIR = ROOT / "data" / "raw" / "planning"
UA = "Mozilla/5.0 (MAPPA data pipeline)"
_SSL = ssl._create_unverified_context()  # PR gov sites often fail default cert checks


def fetch(url: str, dest: Path, timeout: int = 300) -> bool:
    if dest.exists() and dest.stat().st_size > 1000:
        return True
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=timeout, context=_SSL) as r:
            data = r.read()
        if not data.startswith(b"%PDF"):
            print(f"  ! not a PDF: {url[:70]}")
            return False
        dest.write_bytes(data)
        return True
    except Exception as e:
        print(f"  ! download failed: {e}")
        return False


_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")  # keep \t \n \r; drop NUL & other control chars


def _clean(text: str) -> str:
    # Postgres text columns reject NUL (0x00); scanned PDFs also emit stray control bytes.
    return _CTRL.sub("", text)


def extract_text(pdf: Path) -> str:
    doc = fitz.open(pdf)
    try:
        return _clean("\n".join(page.get_text("text") for page in doc)).strip()
    finally:
        doc.close()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tipo", help="filter manifest by tipo (e.g. 'Plan de Recuperación')")
    ap.add_argument("--ids", help="comma-separated doc_ids to fetch")
    ap.add_argument("--skip", default="DOC-033,DOC-034", help="doc_ids already loaded")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--out", type=Path, default=ROOT / "data" / "corpus_batch.json")
    args = ap.parse_args()

    rows = list(csv.DictReader(MANIFEST.open(encoding="utf-8")))
    skip = {s.strip() for s in args.skip.split(",") if s.strip()}
    want_ids = {s.strip() for s in (args.ids or "").split(",") if s.strip()}
    sel = [
        r for r in rows
        if r["doc_id"] not in skip
        and (not want_ids or r["doc_id"] in want_ids)
        and (not args.tipo or args.tipo.lower() in r["tipo"].lower())
    ]
    if args.limit:
        sel = sel[: args.limit]
    print(f"[fetch] {len(sel)} document(s) selected")

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    docs = []
    for i, r in enumerate(sel, 1):
        did = r["doc_id"]
        print(f"[{i}/{len(sel)}] {did} — {r['municipio']}")
        pdf = RAW_DIR / f"{did}.pdf"
        if not fetch(r["url"], pdf):
            continue
        text = extract_text(pdf)
        if len(text) < 500:
            print(f"  ! thin text ({len(text)} chars) — likely scanned/no text layer, skipping")
            continue
        year = None
        try:
            year = int(str(r["year"])[:4])
        except Exception:
            pass
        docs.append({
            "id": did,
            "title": r["title"],
            "jurisdiction": r["municipio"],
            "doc_type": r["tipo"],
            "year": year,
            "url": r["url"],
            "language": "es",
            "tags": [r["municipio"], r["tipo"]],
            "text": text,
        })
        print(f"  ok — {len(text):,} chars")

    args.out.write_text(json.dumps(docs, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[fetch] wrote {len(docs)} docs -> {args.out}")


if __name__ == "__main__":
    main()
