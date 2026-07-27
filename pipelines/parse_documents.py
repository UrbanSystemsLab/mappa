"""Parse PDF / DOCX planning documents into Mappa's corpus JSON schema.

Input:  a directory of .pdf / .docx files (e.g. the local mirror of
        gs://<RAW_BUCKET>/documents/).
Output: one JSON file per source document, shaped like data/documents.json so
        pipelines/ingest_documents.py can chunk + embed it unchanged:

        {
          "id": "...", "title": "...", "jurisdiction": "...", "doc_type": "...",
          "year": 2020, "url": "...", "tags": [...], "language": "es",
          "text": "<full extracted text>",
          "pages": [{"page": 1, "text": "..."}, ...]   # for citation page numbers
        }

Metadata (title/jurisdiction/doc_type/year/url/tags) is read, in priority order:
    1. a sidecar  <file>.meta.json  next to the source file
    2. a shared   manifest.csv       in the input dir (column `filename` matches)
    3. defaults + a warning (title falls back to the filename stem)

Run:
    python -m pipelines.parse_documents --input data/raw/documents --output data/corpus
    # then:
    python -m pipelines.ingest_documents --source data/corpus --commit
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import unicodedata
from pathlib import Path
from typing import Any

META_FIELDS = ("title", "jurisdiction", "doc_type", "year", "url", "tags", "language")


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text[:80] or "doc"


def extract_pdf(path: Path) -> list[dict[str, Any]]:
    import fitz  # PyMuPDF

    pages: list[dict[str, Any]] = []
    with fitz.open(path) as doc:
        for i, page in enumerate(doc, start=1):
            text = _clean(page.get_text("text"))
            if text:
                pages.append({"page": i, "text": text})
    return pages


def extract_docx(path: Path) -> list[dict[str, Any]]:
    import docx  # python-docx

    document = docx.Document(str(path))
    paras = [p.text for p in document.paragraphs if p.text and p.text.strip()]
    text = _clean("\n".join(paras))
    # DOCX has no reliable page model; treat the whole document as one "page".
    return [{"page": 1, "text": text}] if text else []


def _clean(text: str) -> str:
    # Join hyphenated line breaks, collapse whitespace, drop control chars.
    text = text.replace("­", "")
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def load_manifest(input_dir: Path) -> dict[str, dict[str, Any]]:
    manifest_path = input_dir / "manifest.csv"
    if not manifest_path.exists():
        return {}
    rows: dict[str, dict[str, Any]] = {}
    with manifest_path.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            fname = (row.get("filename") or "").strip()
            if fname:
                rows[fname] = row
    return rows


def resolve_metadata(path: Path, manifest: dict[str, dict[str, Any]]) -> tuple[dict[str, Any], list[str]]:
    meta: dict[str, Any] = {}
    warnings: list[str] = []

    sidecar = path.with_suffix(path.suffix + ".meta.json")
    if sidecar.exists():
        meta.update(json.loads(sidecar.read_text(encoding="utf-8")))
    elif path.name in manifest:
        meta.update({k: v for k, v in manifest[path.name].items() if v not in (None, "")})

    # Normalize / default.
    if not meta.get("title"):
        meta["title"] = path.stem
        warnings.append(f"{path.name}: no title metadata, using filename stem")
    meta.setdefault("jurisdiction", "Puerto Rico")
    meta.setdefault("doc_type", "documento")
    meta.setdefault("language", "es")
    meta.setdefault("url", "")

    year = meta.get("year")
    if isinstance(year, str) and year.isdigit():
        meta["year"] = int(year)
    elif not isinstance(year, int):
        m = re.search(r"(19|20)\d{2}", path.stem)
        meta["year"] = int(m.group(0)) if m else None
        if meta["year"] is None:
            warnings.append(f"{path.name}: no year found")

    tags = meta.get("tags", [])
    if isinstance(tags, str):
        tags = [t.strip() for t in re.split(r"[;,|]", tags) if t.strip()]
    meta["tags"] = tags

    return {k: meta.get(k) for k in META_FIELDS}, warnings


def parse_file(path: Path, manifest: dict[str, dict[str, Any]]) -> tuple[dict[str, Any] | None, list[str]]:
    ext = path.suffix.lower()
    if ext == ".pdf":
        pages = extract_pdf(path)
    elif ext == ".docx":
        pages = extract_docx(path)
    else:
        return None, [f"{path.name}: unsupported extension {ext}, skipped"]

    if not pages:
        return None, [f"{path.name}: no extractable text (scanned PDF? needs OCR), skipped"]

    meta, warnings = resolve_metadata(path, manifest)
    full_text = "\n\n".join(p["text"] for p in pages)
    year = meta.get("year")
    record = {
        "id": f"{slugify(meta['title'])}-{year}" if year else slugify(meta["title"]),
        **meta,
        "text": full_text,
        "pages": pages,
    }
    return record, warnings


def main() -> None:
    parser = argparse.ArgumentParser(description="Parse PDF/DOCX into Mappa corpus JSON.")
    parser.add_argument("--input", type=Path, required=True, help="Directory of .pdf/.docx files.")
    parser.add_argument("--output", type=Path, required=True, help="Directory to write corpus JSON files.")
    parser.add_argument("--combined", action="store_true",
                        help="Also write a single combined corpus.json (documents.json-shaped array).")
    args = parser.parse_args()

    if not args.input.is_dir():
        raise SystemExit(f"input dir not found: {args.input}")
    args.output.mkdir(parents=True, exist_ok=True)

    manifest = load_manifest(args.input)
    sources = sorted(p for p in args.input.rglob("*") if p.suffix.lower() in {".pdf", ".docx"})
    print(f"[parse] {len(sources)} source files under {args.input}")

    records: list[dict[str, Any]] = []
    all_warnings: list[str] = []
    for path in sources:
        record, warnings = parse_file(path, manifest)
        all_warnings.extend(warnings)
        if record is None:
            continue
        out_path = args.output / f"{record['id']}.json"
        out_path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        records.append(record)
        print(f"[parse] {path.name} → {out_path.name} "
              f"({len(record['pages'])} pages, {len(record['text'])} chars)")

    if args.combined:
        combined = args.output / "corpus.json"
        # Strip per-page detail from the combined array to match documents.json shape.
        slim = [{k: v for k, v in r.items() if k != "pages"} for r in records]
        combined.write_text(json.dumps(slim, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[parse] wrote combined {combined} ({len(slim)} docs)")

    print(f"[parse] done. {len(records)} parsed, {len(sources) - len(records)} skipped.")
    if all_warnings:
        print(f"[parse] {len(all_warnings)} warnings:")
        for w in all_warnings:
            print(f"  - {w}")


if __name__ == "__main__":
    main()
