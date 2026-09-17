"""OCR a sample of La Maraña's scanned documents, to judge quality before committing.

73 of the PDFs they supplied have no text layer, so they are invisible to the
assistant. Before running OCR over all of them - and before promising them
anything - this renders a few pages of a handful of documents and reports what
came back, so a person can read the output and decide whether it is good enough
for legal text.

Spanish matters here: the corpus is Spanish, and accents and ñ carry meaning
(ano / año). Output that drops them is worse than no output, because it would be
cited as if it were the document.

Run:
    python -m pipelines.ocr_pilot --pages 3
"""

from __future__ import annotations

import argparse
import re
import subprocess
import tempfile
from pathlib import Path

ROOT = Path("data/raw/lamarana_docs/Documentos de planificacion")

# One from each folder that holds scans, so the sample covers a law, a territorial
# plan, a housing regulation, a supplementary document and a map sheet.
SAMPLE = [
    "Ambiente/Leyes/DOC-001.pdf",
    "Planes Territoriales /POT-007.pdf",
    "Vivienda/Reglamentos/RV-002.pdf",
    "Documentos suplementarios/7459_Enmienda_al_Reglamento_para_la_Adquisicion_y_"
    "Disposicion_de_Propiedades_Inmuebles_Vigencia_inmediata.pdf",
    "Ambiente/Mapas_JP/GIS-001.pdf",
]

ACCENTED = re.compile(r"[áéíóúñüÁÉÍÓÚÑÜ]")
# Tesseract failing on a page tends to produce punctuation soup rather than words.
WORDS = re.compile(r"[A-Za-zÀ-ÿ]{3,}")


def ocr_pdf(path: Path, pages: int, dpi: int = 300) -> str:
    """Render the first pages to images and read them with Spanish Tesseract."""
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(
            ["pdftoppm", "-r", str(dpi), "-f", "1", "-l", str(pages), "-png",
             str(path), f"{tmp}/pg"],
            check=True, capture_output=True,
        )
        text = []
        for img in sorted(Path(tmp).glob("pg*.png")):
            out = subprocess.run(
                ["tesseract", str(img), "stdout", "-l", "spa", "--psm", "1"],
                check=True, capture_output=True, text=True,
            )
            text.append(out.stdout)
    return "\n".join(text)


def score(text: str) -> tuple[int, int, float]:
    """Characters, real words, and the share of characters that are letters.

    A low letter share means the page came back as noise, which is the failure
    mode that matters - noise still looks like text to an ingest pipeline.
    """
    words = WORDS.findall(text)
    letters = sum(1 for c in text if c.isalpha())
    return len(text), len(words), (letters / len(text) if text else 0.0)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pages", type=int, default=3)
    args = ap.parse_args()

    out_dir = Path("data/eval/ocr_pilot")
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"[ocr] sampling {len(SAMPLE)} documents, first {args.pages} pages each\n")
    for rel in SAMPLE:
        path = ROOT / rel
        if not path.exists():
            print(f"  MISSING  {rel}")
            continue
        try:
            text = ocr_pdf(path, args.pages)
        except subprocess.CalledProcessError as exc:
            print(f"  FAILED   {path.name}: {exc.stderr.decode()[:90]}")
            continue
        chars, words, letter_share = score(text)
        accents = len(ACCENTED.findall(text))
        (out_dir / f"{path.stem}.txt").write_text(text, encoding="utf-8")
        print(f"  {path.name[:46]:46}")
        print(f"      {chars:>7,} chars  {words:>6,} words  "
              f"{letter_share:.0%} letters  {accents:>4} accented")
        snippet = " ".join(text.split())[:150]
        print(f"      {snippet}\n")
    print(f"[ocr] full text written to {out_dir} - read it before trusting the numbers")


if __name__ == "__main__":
    main()
