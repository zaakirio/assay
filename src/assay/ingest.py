"""PDF to text. Uses pypdf's layout extraction mode so column alignment
survives as whitespace; the model relies on that spatial signal to associate
quantities with the right line items."""

from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader


@dataclass
class Document:
    doc_id: str
    path: Path
    pages: list[str]

    @property
    def text(self) -> str:
        if len(self.pages) == 1:
            return self.pages[0]
        return "\n\n".join(
            f"--- page {i + 1} of {len(self.pages)} ---\n{p}"
            for i, p in enumerate(self.pages)
        )


def _clean(page_text: str) -> str:
    lines = [ln.rstrip() for ln in page_text.splitlines()]
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines)


def ingest(path: Path) -> Document:
    # SROIE receipts arrive as pre-OCR'd plain text, one file per receipt.
    if path.suffix == ".txt":
        return Document(doc_id=path.stem, path=path, pages=[_clean(path.read_text())])
    reader = PdfReader(str(path))
    pages = [_clean(p.extract_text(extraction_mode="layout")) for p in reader.pages]
    return Document(doc_id=path.stem, path=path, pages=pages)
