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


# --- Fix 1: sniff gate handles empty / tiny payloads ---


def test_sniff_handles_empty_bytes() -> None:
    assert sniff_matches_extension(b"", ".txt") is True
    assert sniff_matches_extension(b"", ".pdf") is False


def test_sniff_handles_tiny_payload() -> None:
    assert sniff_matches_extension(b"x", ".txt") is True


# --- Fix 2: text parser rejects NUL bytes ---


def test_text_parser_rejects_nul_bytes() -> None:
    parser = get_parser(".txt")
    with pytest.raises(ParseFailedError):
        parser.parse(b"\x7fELF" + b"\x00" * 50, "fake.txt")


# --- Fix 3: build_enriched_text output format ---


def test_build_enriched_text_locations() -> None:
    from app.ingestion.chunking import build_enriched_text

    assert build_enriched_text("a.pdf", "body", page_number=3) == (
        "File: a.pdf | Page: 3\nContent: body"
    )
    assert build_enriched_text("a.xlsx", "body", sheet_name="Q1") == (
        "File: a.xlsx | Sheet: Q1\nContent: body"
    )
    # Page wins when both present
    assert "| Page: 2" in build_enriched_text(
        "a.pdf", "b", page_number=2, sheet_name="X"
    )
    assert build_enriched_text("a.txt", "body") == "File: a.txt\nContent: body"


# --- Fix 4: registry case-insensitivity ---


def test_get_parser_is_case_insensitive() -> None:
    assert get_parser(".TXT") is not None


# --- pdf parser ---


def test_pdf_parser_extracts_text_per_page() -> None:
    parser = get_parser(".pdf")
    data = (FIXTURES / "sample.pdf").read_bytes()
    parsed = parser.parse(data, "sample.pdf")
    assert parsed.page_count == 2
    assert parsed.needs_ocr_pages == []
    page1 = next(b for b in parsed.blocks if b.page_number == 1)
    assert "Photosynthesis" in page1.text


def test_pdf_parser_flags_scanned_pages_for_ocr() -> None:
    parser = get_parser(".pdf")
    data = (FIXTURES / "scanned.pdf").read_bytes()
    parsed = parser.parse(data, "scanned.pdf")
    assert parsed.page_count == 2
    assert parsed.needs_ocr_pages == [1, 2]
    assert parsed.blocks == []


def test_pdf_parser_rejects_over_page_limit() -> None:
    from io import BytesIO

    from pypdf import PdfWriter

    from app.shared.errors import PageLimitExceededError

    writer = PdfWriter()
    for _ in range(51):
        writer.add_blank_page(width=200, height=200)
    buf = BytesIO()
    writer.write(buf)

    parser = get_parser(".pdf")
    with pytest.raises(PageLimitExceededError):
        parser.parse(buf.getvalue(), "big.pdf")


def test_pdf_parser_rejects_corrupt_file() -> None:
    parser = get_parser(".pdf")
    with pytest.raises(ParseFailedError):
        parser.parse(b"%PDF-1.4 garbage not a real pdf", "corrupt.pdf")


# --- docx parser ---


def test_docx_parser_extracts_paragraphs_and_tables() -> None:
    parser = get_parser(".docx")
    data = (FIXTURES / "sample.docx").read_bytes()
    parsed = parser.parse(data, "sample.docx")
    text = "\n".join(b.text for b in parsed.blocks)
    assert "powerhouse of the cell" in text
    assert "| Organelle | Function |" in text  # tables come out as markdown
    assert "Ribosome" in text


def test_docx_parser_rejects_corrupt_file() -> None:
    parser = get_parser(".docx")
    with pytest.raises(ParseFailedError):
        parser.parse(b"not a zip at all", "corrupt.docx")


# --- docx zip-bomb guard ---


def test_docx_zip_bomb_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.ingestion import office

    data = (FIXTURES / "sample.docx").read_bytes()
    monkeypatch.setattr(office, "MAX_DECOMPRESSED_BYTES", 10)
    with pytest.raises(ParseFailedError, match="decompresses too large"):
        office.check_zip_bomb(data)


# --- xlsx parser ---


def test_xlsx_parser_emits_markdown_tables_with_header() -> None:
    parser = get_parser(".xlsx")
    data = (FIXTURES / "sample.xlsx").read_bytes()
    parsed = parser.parse(data, "sample.xlsx")
    assert len(parsed.blocks) == 1
    block = parsed.blocks[0]
    assert block.is_atomic is True
    assert block.sheet_name == "Grades"
    assert "| Student | Subject | Grade |" in block.text
    assert "| Ana | Math | 95 |" in block.text


def test_xlsx_parser_repeats_header_across_row_chunks() -> None:
    from io import BytesIO

    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Big"
    ws.append(["id", "value"])
    for i in range(75):  # 75 data rows -> 3 blocks at 30 rows each
        ws.append([i, f"v{i}"])
    buf = BytesIO()
    wb.save(buf)

    parser = get_parser(".xlsx")
    parsed = parser.parse(buf.getvalue(), "big.xlsx")
    assert len(parsed.blocks) == 3
    for block in parsed.blocks:
        assert block.text.startswith("| id | value |")
        assert block.is_atomic is True


def test_xlsx_parser_rejects_corrupt_file() -> None:
    parser = get_parser(".xlsx")
    with pytest.raises(ParseFailedError):
        parser.parse(b"definitely not xlsx", "corrupt.xlsx")


# --- xlsx zip-bomb guard ---


def test_xlsx_zip_bomb_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.ingestion import office

    data = (FIXTURES / "sample.xlsx").read_bytes()
    monkeypatch.setattr(office, "MAX_DECOMPRESSED_BYTES", 10)
    with pytest.raises(ParseFailedError, match="decompresses too large"):
        office.check_zip_bomb(data)


# --- image parser (vision is faked by the autouse conftest fixture) ---


async def test_image_parser_uses_vision() -> None:
    parser = get_parser(".png")
    data = (FIXTURES / "sample.png").read_bytes()
    parsed = parser.parse(data, "sample.png")
    # Image parsing defers extraction: it flags a single pseudo-page for OCR
    assert parsed.page_count == 1
    assert parsed.needs_ocr_pages == [1]
    assert parsed.blocks == []
