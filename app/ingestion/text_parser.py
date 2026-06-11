from __future__ import annotations

from app.ingestion.base import ParsedBlock, ParsedDocument
from app.shared.errors import ParseFailedError


class TextParser:
    def parse(self, data: bytes, filename: str) -> ParsedDocument:
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ParseFailedError("File is not valid UTF-8 text") from exc
        if not text.strip():
            raise ParseFailedError("File contains no text")
        return ParsedDocument(blocks=[ParsedBlock(text=text)])
