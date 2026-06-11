from __future__ import annotations

from io import BytesIO

from pypdf import PdfReader

from app.ingestion.base import ParsedBlock, ParsedDocument
from app.shared.config import get_settings
from app.shared.errors import PageLimitExceededError, ParseFailedError

# Pages with fewer extractable characters than this are treated as scanned.
MIN_TEXT_CHARS = 20


class PdfParser:
    def parse(self, data: bytes, filename: str) -> ParsedDocument:
        try:
            reader = PdfReader(BytesIO(data))
            if reader.is_encrypted:
                raise ParseFailedError("Encrypted PDFs are not supported")
            page_count = len(reader.pages)
        except ParseFailedError:
            raise
        except Exception as exc:
            raise ParseFailedError("Could not read the PDF file") from exc

        max_pages = get_settings().MAX_PDF_PAGES
        if page_count > max_pages:
            raise PageLimitExceededError(
                f"PDF has {page_count} pages; the limit is {max_pages}"
            )

        blocks: list[ParsedBlock] = []
        needs_ocr: list[int] = []
        for i, page in enumerate(reader.pages, start=1):
            try:
                text = (page.extract_text() or "").strip()
            except (
                Exception
            ):  # pypdf raises varied internals; a bad page must not kill the doc
                text = ""
            if len(text) >= MIN_TEXT_CHARS:
                blocks.append(ParsedBlock(text=text, page_number=i))
            else:
                needs_ocr.append(i)

        return ParsedDocument(
            blocks=blocks, page_count=page_count, needs_ocr_pages=needs_ocr
        )
