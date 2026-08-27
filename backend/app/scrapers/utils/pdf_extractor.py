"""PDF text extraction via PyMuPDF.

Scanned PDFs come back nearly empty; `needs_ocr()` flags those so the caller can
route them to OCR (Milestone 11) rather than feeding blank text to the AI layer.
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)

MAX_PAGES = 20
OCR_TEXT_THRESHOLD = 200  # chars; below this a text-layer PDF is suspect


def extract_pdf_text(data: bytes, max_pages: int = MAX_PAGES) -> str:
    try:
        import fitz  # PyMuPDF
    except ImportError:  # pragma: no cover - dependency guard
        log.warning("PyMuPDF not installed; cannot extract PDF text")
        return ""

    try:
        with fitz.open(stream=data, filetype="pdf") as doc:
            pages = [doc[i].get_text() for i in range(min(len(doc), max_pages))]
        return "\n".join(pages).strip()
    except Exception as exc:
        log.warning("PDF extraction failed: %s", exc)
        return ""


def needs_ocr(text: str) -> bool:
    return len(text.strip()) < OCR_TEXT_THRESHOLD
