from __future__ import annotations

from app.ingestion.base import ParsedDocument


class ImageParser:
    """Images defer extraction to the OCR stage: one pseudo-page flagged for vision."""

    def parse(self, data: bytes, filename: str) -> ParsedDocument:
        return ParsedDocument(blocks=[], page_count=1, needs_ocr_pages=[1])
