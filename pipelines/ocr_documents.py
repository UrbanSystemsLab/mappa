"""OCR the scanned documents La Maraña supplied, so they stop being invisible.

73 of their PDFs are scans with no text layer. The pilot showed Tesseract reads
their body prose well in Spanish - accents and ñ intact - but mangles stylised
cover pages, and returns noise for map sheets. So:

  * Identity never comes from OCR. The document ID, title and year come from
    their inventory, as they already do for every other document. An OCR'd cover
    page that reads "Ley Núm. 11Z- ZO!" can never become a citation.
  * A document whose OCR is mostly not letters is a map or a form, not prose. It
    is left out rather than ingested as noise that would be quoted back at a user.

Output is one text file per document, so a rerun skips what is already done and
a person can read any of it.

Run:
    python -m pipelines.ocr_documents --limit 5      # try a few
    python -m pipelines.ocr_documents                # all of them
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import tempfile
from pathlib import Path

import psycopg2

ROOT = Path("data/raw/lamarana_docs")
OUT = Path("data/raw/ocr")
DPI = 300

WORDS = re.compile(r"[A-Za-zÀ-ÿ]{3,}")
CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")

# What separates a scanned document from a scanned map is the share of characters
# that are letters, not how many words came back. Their map sheets land at 67-73%
# (coordinates, grid labels, fragments); real documents run 77-81%. A word floor
# of 400 rejected a genuine 314-word regulation, so it is only there to catch a
# page or two of noise.
MIN_LETTER_SHARE = 0.75
MIN_WORDS = 120


def ocr_page_range(pdf: Path, first: int, last: int) -> str:
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(
            ["pdftoppm", "-r", str(DPI), "-f", str(first), "-l", str(last), "-png",
             str(pdf), f"{tmp}/pg"],
            check=True, capture_output=True,
        )
        out = []
        for img in sorted(Path(tmp).glob("pg*.png")):
            res = subprocess.run(
                ["tesseract", str(img), "stdout", "-l", "spa", "--psm", "1"],
                check=True, capture_output=True, text=True,
            )
            out.append(res.stdout)
    return "\n".join(out)


def ocr_document(pdf: Path, chunk: int = 10) -> str:
    """OCR a whole document a few pages at a time, so memory stays flat and a
    large plan does not hold hundreds of rendered images at once."""
    import fitz
    doc = fitz.open(pdf)
    pages = doc.page_count
    doc.close()
    parts = []
    for start in range(1, pages + 1, chunk):
        parts.append(ocr_page_range(pdf, start, min(start + chunk - 1, pages)))
    return CTRL.sub("", "\n".join(parts)).strip()


def is_prose(text: str) -> tuple[bool, str]:
    """Whether this reads as a document rather than a scanned map."""
    if not text:
        return False, "no output"
    words = len(WORDS.findall(text))
    letters = sum(1 for c in text if c.isalpha())
    share = letters / len(text)
    if share < MIN_LETTER_SHARE or words < MIN_WORDS:
        return False, f"image-only ({share:.0%} letters, {words} words)"
    return True, f"{share:.0%} letters, {words} words"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="stop after N documents")
    ap.add_argument("--redo", action="store_true", help="re-OCR files already done")
    args = ap.parse_args()
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        raise SystemExit("DATABASE_URL not set")

    OUT.mkdir(parents=True, exist_ok=True)
    conn = psycopg2.connect(dsn)
    conn.autocommit = True
    cur = conn.cursor()

    scans = sorted(p for p in ROOT.glob("**/*.pdf"))
    todo = []
    for pdf in scans:
        import fitz
        try:
            doc = fitz.open(pdf)
            has_text = any(len(pg.get_text("text").strip()) > 40 for pg in doc)
            doc.close()
        except Exception:
            continue
        if not has_text:
            todo.append(pdf)

    print(f"[ocr] {len(todo)} scanned documents to read")
    done = ok = skipped = 0
    for pdf in todo:
        target = OUT / f"{pdf.stem}.txt"
        if target.exists() and not args.redo:
            skipped += 1
            continue
        if args.limit and done >= args.limit:
            break
        try:
            text = ocr_document(pdf)
        except subprocess.CalledProcessError as exc:
            print(f"  FAILED  {pdf.name[:44]:44} {exc.stderr.decode()[:60]}")
            continue
        prose, why = is_prose(text)
        done += 1
        if not prose:
            print(f"  image   {pdf.name[:44]:44} {why}")
            cur.execute("""UPDATE document_registry SET load_note=%s
                           WHERE doc_id = %s""",
                        (f"scanned; OCR found no prose ({why})", pdf.stem))
            continue
        target.write_text(text, encoding="utf-8")
        ok += 1
        print(f"  read    {pdf.name[:44]:44} {len(text):>8,} chars  {why}")

    print(f"\n[ocr] {ok} documents read, {done - ok} image-only, "
          f"{skipped} already done -> {OUT}")


if __name__ == "__main__":
    main()
