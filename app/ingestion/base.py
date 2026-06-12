from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class ParsedBlock:
    """One unit of extracted content with its source location."""

    text: str
    page_number: int | None = None
    sheet_name: str | None = None
    is_atomic: bool = False  # True = pre-chunked (e.g. xlsx tables); never re-split


@dataclass
class ParsedDocument:
    """Common output of every parser."""

    blocks: list[ParsedBlock]
    page_count: int | None = None
    needs_ocr_pages: list[int] = field(default_factory=list)  # 1-based page numbers


@dataclass
class Chunk:
    """A chunk ready for embedding, carrying its source location."""

    text: str
    page_number: int | None = None
    sheet_name: str | None = None


class Parser(Protocol):
    def parse(self, data: bytes, filename: str) -> ParsedDocument: ...
