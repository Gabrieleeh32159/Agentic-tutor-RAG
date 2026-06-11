from __future__ import annotations

from pathlib import Path

import pytest

from app.ingestion.base import ParsedBlock, ParsedDocument
from app.ingestion.chunking import chunk_blocks
from app.ingestion.registry import SUPPORTED_TYPES, get_parser, sniff_matches_extension
from app.shared.errors import ParseFailedError

FIXTURES = Path(__file__).parent / "fixtures"


# --- text parser ---


def test_text_parser_returns_single_block() -> None:
    parser = get_parser(".txt")
    parsed = parser.parse(b"Newton's first law.", "notes.txt")
    assert isinstance(parsed, ParsedDocument)
    assert parsed.page_count is None
    assert parsed.needs_ocr_pages == []
    assert len(parsed.blocks) == 1
    assert "Newton" in parsed.blocks[0].text


def test_text_parser_rejects_invalid_utf8() -> None:
    parser = get_parser(".txt")
    with pytest.raises(ParseFailedError):
        parser.parse(b"\xff\xfe\x00\x01", "binary.txt")


def test_text_parser_rejects_empty() -> None:
    parser = get_parser(".md")
    with pytest.raises(ParseFailedError):
        parser.parse(b"   \n", "empty.md")


# --- chunking ---


def test_chunk_blocks_carries_page_numbers() -> None:
    blocks = [
        ParsedBlock(text="First page text. " * 30, page_number=1),
        ParsedBlock(text="Second page text. " * 30, page_number=2),
    ]
    chunks = chunk_blocks(blocks)
    assert len(chunks) >= 2
    pages = {c.page_number for c in chunks}
    assert pages == {1, 2}


def test_chunk_blocks_atomic_blocks_not_split() -> None:
    long_table = "| a | b |\n" * 200
    blocks = [ParsedBlock(text=long_table, sheet_name="Q1", is_atomic=True)]
    chunks = chunk_blocks(blocks)
    assert len(chunks) == 1
    assert chunks[0].text == long_table
    assert chunks[0].sheet_name == "Q1"


def test_chunk_blocks_respects_max_chunks() -> None:
    blocks = [
        ParsedBlock(text=f"Paragraph {i}. " * 40, page_number=i) for i in range(80)
    ]
    chunks = chunk_blocks(blocks, max_chunks=10)
    assert len(chunks) == 10


# --- registry ---


def test_registry_covers_all_planned_types() -> None:
    assert set(SUPPORTED_TYPES) == {
        ".txt",
        ".md",
        ".pdf",
        ".docx",
        ".xlsx",
        ".png",
        ".jpg",
        ".jpeg",
        ".webp",
    }


def test_registry_unknown_extension() -> None:
    assert get_parser(".exe", default=None) is None


def test_sniff_rejects_mismatched_signature() -> None:
    # PNG bytes pretending to be a PDF
    png = (FIXTURES / "sample.png").read_bytes()
    assert sniff_matches_extension(png, ".pdf") is False
    assert sniff_matches_extension(png, ".png") is True


def test_sniff_accepts_plain_text() -> None:
    # txt/md have no magic signature - any non-matching-binary content passes
    assert sniff_matches_extension(b"just words", ".txt") is True
    assert sniff_matches_extension(b"# heading", ".md") is True


def test_sniff_accepts_real_fixtures() -> None:
    for name, ext in [
        ("sample.pdf", ".pdf"),
        ("sample.docx", ".docx"),
        ("sample.xlsx", ".xlsx"),
        ("sample.png", ".png"),
    ]:
        data = (FIXTURES / name).read_bytes()
        assert sniff_matches_extension(data, ext) is True, name
