"""Fetch planning-document PDFs from their public URLs into the GCS raw bucket.

Reads data/planning_manifest.csv (doc_id,title,year,municipio,tipo,url) and, for
each row, downloads the PDF and uploads it to
gs://<bucket>/<prefix>/<doc_id>.pdf.

Idempotent: a document already present in the bucket is skipped, so re-running
resumes where it left off (useful on a slow connection).

Run:
    python -m pipelines.fetch_planning_pdfs --commit
    python -m pipelines.fetch_planning_pdfs --commit --limit 50
"""

from __future__ import annotations

import argparse
import csv
import ssl
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MANIFEST = ROOT / "data" / "planning_manifest.csv"
UA = "Mozilla/5.0 (MAPPA data pipeline)"
# PR government sites often present certificates that fail default verification.
_SSL_CTX = ssl._create_unverified_context()


def fetch(url: str, timeout: int = 300) -> bytes | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=timeout, context=_SSL_CTX) as r:
            if r.status != 200:
                return None
            data = r.read()
        return data if len(data) > 1000 else None
    except Exception:
        return None


def main() -> None:
    ap = argparse.ArgumentParser(description="Fetch planning PDFs into the raw bucket.")
    ap.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    ap.add_argument("--bucket", default="mappa-lamarana-aecc-raw")
    ap.add_argument("--prefix", default="documents/planning/")
    ap.add_argument("--limit", type=int, default=0, help="Max docs this run (0 = all).")
    ap.add_argument("--commit", action="store_true", help="Actually upload. Else dry run.")
    args = ap.parse_args()

    rows = list(csv.DictReader(args.manifest.open(encoding="utf-8")))
    print(f"[fetch] {len(rows)} documents in manifest")

    from google.cloud import storage

    bucket = storage.Client().bucket(args.bucket)
    uploaded = skipped = failed = 0
    for i, row in enumerate(rows, 1):
        if args.limit and uploaded + failed >= args.limit:
            print(f"[fetch] reached limit ({args.limit})")
            break
        doc_id, url = row["doc_id"], row["url"]
        blob = bucket.blob(f"{args.prefix}{doc_id}.pdf")
        if blob.exists():
            skipped += 1
            continue
        if not args.commit:
            print(f"[fetch] DRY would fetch {doc_id} <- {url}")
            continue
        data = fetch(url)
        if data is None:
            failed += 1
            print(f"[fetch] FAIL {doc_id} ({url})")
            continue
        blob.upload_from_string(data, content_type="application/pdf")
        uploaded += 1
        print(f"[fetch] ok {doc_id} ({len(data)//1024} KB)  [{uploaded} up / {skipped} skip / {failed} fail]")

    print(f"[fetch] done. uploaded={uploaded} skipped={skipped} failed={failed}")


if __name__ == "__main__":
    main()
