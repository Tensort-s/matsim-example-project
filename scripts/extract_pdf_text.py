from __future__ import annotations

import argparse
from pathlib import Path

import fitz


def extract_pdf_text(pdf_path: Path, output_path: Path) -> None:
    doc = fitz.open(pdf_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("w", encoding="utf-8", newline="\n") as out:
        out.write(f"# Source: {pdf_path}\n")
        out.write(f"# Pages: {doc.page_count}\n\n")

        for page_number, page in enumerate(doc, start=1):
            text = page.get_text("text")
            out.write(f"\n\n--- Page {page_number} ---\n\n")
            out.write(text)


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract text from a PDF with PyMuPDF.")
    parser.add_argument("pdf", type=Path, help="Input PDF path")
    parser.add_argument("output", type=Path, help="Output text path")
    args = parser.parse_args()

    extract_pdf_text(args.pdf, args.output)


if __name__ == "__main__":
    main()
