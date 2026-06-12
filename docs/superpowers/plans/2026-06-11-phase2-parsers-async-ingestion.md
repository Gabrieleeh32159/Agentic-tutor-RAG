# Phase 2: Parser Registry + Async Ingestion + Vision OCR — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Uploads accept PDF (digital + scanned), Word (.docx), Excel (.xlsx), images (.png/.jpg/.webp), and txt/md; processing runs in a detached background task with live status/stage/progress; scanned pages and images are extracted by a vision LLM.

**Architecture:** New `app/ingestion/` package: a MIME/extension-keyed parser registry where every parser returns a common `ParsedDocument` (blocks with page/sheet metadata + pages flagged for OCR). `process_document` orchestrates parse → OCR → chunk → embed → save in an `asyncio.create_task` (held in a module-level set), committing every stage transition so polling `GET /sessions/{id}/documents` sees progress. ALL parse failures now surface uniformly as `status=failed` rows (the 202 contract); the router only rejects what it can check cheaply (extension, size, MIME signature, per-session doc cap). Startup reconciliation marks rows orphaned by restarts as `failed/interrupted`.

**Tech Stack:** pypdf (text extraction), pypdfium2 (page rasterization, pure wheel), python-docx, openpyxl (read_only), puremagic (MIME sniff) — all prod deps; reportlab (dev-only, fixture generation). Vision: `gpt-4o-mini` via a new `get_vision_model()` using the existing LangChain abstraction.

**This is plan 2 of 7.** Spec: `docs/superpowers/specs/2026-06-10-ask-your-pdfs-design.md`. Phase 1 (sessions restructure) is merged on this branch; suite = 48 tests, green, ~4s on local Postgres.

**Environment:** local Docker Postgres running (`docker start challenge_postgres` if needed); `.env` points at localhost (NOT Neon). Tests are key-free (conftest fakes embeddings/LLM; this phase adds a fake for vision).

**Breaking change to Phase-1 tests (intentional):** upload no longer processes inline — it returns `202 {status: "pending"}` and a background task does the work. Existing tests in `test_documents.py`, `test_search.py`, `test_chat.py` that assert `status == "ready"` right after upload must be adapted to await the new `wait_for_ingestion()` test helper. UTF-8/empty-file failures move from synchronous 422s to `status=failed` rows (uniform failure surface across all formats — per Phase-1 review note).

---

### Task 1: Dependencies + test fixtures

**Files:**
- Modify: `pyproject.toml`
- Create: `scripts/make_fixtures.py`, `tests/fixtures/sample.pdf`, `tests/fixtures/scanned.pdf`, `tests/fixtures/sample.docx`, `tests/fixtures/sample.xlsx`, `tests/fixtures/sample.png`, `tests/fixtures/sample.txt`

- [ ] **Step 1: Add dependencies**

In `pyproject.toml` `dependencies`, add:

```toml
    "pypdf>=5.0.0",
    "pypdfium2>=4.30.0",
    "python-docx>=1.1.0",
    "openpyxl>=3.1.0",
    "puremagic>=1.27",
```

In `[dependency-groups] dev`, add `"reportlab>=4.2.0"`. Run `uv sync`.

- [ ] **Step 2: Create `scripts/make_fixtures.py`**

```python
"""Generate the committed test fixtures in tests/fixtures/.

Run once; the outputs are committed so tests stay deterministic:

    uv run python scripts/make_fixtures.py
"""

from __future__ import annotations

import base64
import sys
import zipfile
from io import BytesIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

FIXTURES = Path(__file__).parent.parent / "tests" / "fixtures"

# A valid 1x1 red PNG (vision extraction is faked in tests, so content is irrelevant)
PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGP4z8DwHwAFAAH/q842iQAAAABJRU5ErkJggg=="
)


def make_sample_pdf() -> None:
    """Two pages with real extractable text."""
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas

    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    c.drawString(72, 720, "Photosynthesis converts light energy into chemical energy.")
    c.drawString(72, 700, "Chlorophyll absorbs blue and red light most efficiently.")
    c.showPage()
    c.drawString(72, 720, "The Calvin cycle fixes carbon dioxide into glucose.")
    c.showPage()
    c.save()
    (FIXTURES / "sample.pdf").write_bytes(buf.getvalue())


def make_scanned_pdf() -> None:
    """Two pages with NO extractable text (image-only / blank) -> triggers OCR."""
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas

    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    # Draw rectangles only - no text layer, like a scan without OCR
    c.rect(72, 600, 400, 100, fill=1)
    c.showPage()
    c.rect(72, 600, 400, 100, fill=1)
    c.showPage()
    c.save()
    (FIXTURES / "scanned.pdf").write_bytes(buf.getvalue())


def make_sample_docx() -> None:
    import docx

    document = docx.Document()
    document.add_heading("Mitochondria", level=1)
    document.add_paragraph("Mitochondria are the powerhouse of the cell.")
    table = document.add_table(rows=2, cols=2)
    table.rows[0].cells[0].text = "Organelle"
    table.rows[0].cells[1].text = "Function"
    table.rows[1].cells[0].text = "Ribosome"
    table.rows[1].cells[1].text = "Protein synthesis"
    document.save(FIXTURES / "sample.docx")


def make_sample_xlsx() -> None:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Grades"
    ws.append(["Student", "Subject", "Grade"])
    ws.append(["Ana", "Math", 95])
    ws.append(["Luis", "Biology", 88])
    wb.save(FIXTURES / "sample.xlsx")


def main() -> None:
    FIXTURES.mkdir(parents=True, exist_ok=True)
    make_sample_pdf()
    make_scanned_pdf()
    make_sample_docx()
    make_sample_xlsx()
    (FIXTURES / "sample.png").write_bytes(PNG_1X1)
    (FIXTURES / "sample.txt").write_text(
        "Newton's first law states that objects in motion stay in motion."
    )
    # Sanity: every fixture exists and is non-empty
    for name in [
        "sample.pdf", "scanned.pdf", "sample.docx",
        "sample.xlsx", "sample.png", "sample.txt",
    ]:
        path = FIXTURES / name
        assert path.stat().st_size > 0, name
    # docx/xlsx are zips - verify they open
    for name in ["sample.docx", "sample.xlsx"]:
        assert zipfile.ZipFile(FIXTURES / name).namelist()
    print(f"Fixtures written to {FIXTURES}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Generate and verify fixtures**

Run: `uv run python scripts/make_fixtures.py`
Expected: "Fixtures written to .../tests/fixtures". Then verify pypdf can read both PDFs and that scanned.pdf has no text:

```bash
uv run python -c "
from pypdf import PdfReader
r = PdfReader('tests/fixtures/sample.pdf')
assert len(r.pages) == 2 and 'Photosynthesis' in r.pages[0].extract_text()
r2 = PdfReader('tests/fixtures/scanned.pdf')
assert len(r2.pages) == 2 and not r2.pages[0].extract_text().strip()
print('PDF fixtures OK')
"
```

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml uv.lock scripts/make_fixtures.py tests/fixtures/
git commit -m "feat: parsing deps + committed test fixtures with generator script"
```

---

### Task 2: Ingestion core — base types, text parser, chunking, registry (unit-tested, no DB)

**Files:**
- Create: `app/ingestion/__init__.py` (empty), `app/ingestion/base.py`, `app/ingestion/text_parser.py`, `app/ingestion/chunking.py`, `app/ingestion/registry.py`
- Test: `tests/test_ingestion_parsers.py` (new; pure unit tests, no DB/client needed)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_ingestion_parsers.py`:

```python
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
    blocks = [ParsedBlock(text=f"Paragraph {i}. " * 40, page_number=i) for i in range(80)]
    chunks = chunk_blocks(blocks, max_chunks=10)
    assert len(chunks) == 10


# --- registry ---


def test_registry_covers_all_planned_types() -> None:
    assert set(SUPPORTED_TYPES) == {
        ".txt", ".md", ".pdf", ".docx", ".xlsx", ".png", ".jpg", ".jpeg", ".webp"
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
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_ingestion_parsers.py -v`
Expected: collection FAIL (`ModuleNotFoundError: app.ingestion`).

- [ ] **Step 3: Implement `app/ingestion/base.py`**

```python
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
```

- [ ] **Step 4: Implement `app/ingestion/text_parser.py`**

```python
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
```

- [ ] **Step 5: Implement `app/ingestion/chunking.py`**

The splitter and enrichment move here from `app/documents/service.py` (Task 5 deletes them there).

```python
from __future__ import annotations

import logging

from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.ingestion.base import Chunk, ParsedBlock

logger = logging.getLogger(__name__)

_splitter = RecursiveCharacterTextSplitter(
    separators=["\n\n", "\n", r"(?<=\. )"],
    is_separator_regex=True,
    chunk_size=300,
    chunk_overlap=50,
)


def chunk_blocks(blocks: list[ParsedBlock], max_chunks: int | None = None) -> list[Chunk]:
    """Split parsed blocks into embeddable chunks, preserving source location.

    Atomic blocks (pre-chunked, e.g. xlsx markdown tables) pass through unsplit.
    """
    chunks: list[Chunk] = []
    for block in blocks:
        if block.is_atomic:
            chunks.append(
                Chunk(
                    text=block.text,
                    page_number=block.page_number,
                    sheet_name=block.sheet_name,
                )
            )
            continue
        for piece in _splitter.split_text(block.text):
            chunks.append(
                Chunk(
                    text=piece,
                    page_number=block.page_number,
                    sheet_name=block.sheet_name,
                )
            )
    if max_chunks is not None and len(chunks) > max_chunks:
        logger.warning(
            "Document produced %d chunks; truncating to %d", len(chunks), max_chunks
        )
        chunks = chunks[:max_chunks]
    return chunks


def build_enriched_text(
    filename: str,
    chunk: str,
    page_number: int | None = None,
    sheet_name: str | None = None,
) -> str:
    """Text that actually gets embedded: file context + chunk content."""
    location = ""
    if page_number is not None:
        location = f" | Page: {page_number}"
    elif sheet_name is not None:
        location = f" | Sheet: {sheet_name}"
    return f"File: {filename}{location}\nContent: {chunk}"
```

- [ ] **Step 6: Implement `app/ingestion/registry.py`**

```python
from __future__ import annotations

import puremagic

from app.ingestion.base import Parser
from app.ingestion.text_parser import TextParser

# extension -> canonical MIME type stored on the Document row
SUPPORTED_TYPES: dict[str, str] = {
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}

# Binary extensions and the signature prefixes puremagic must agree with.
# txt/md have no signature; they pass unless the bytes match a known binary type.
_BINARY_EXT_MATCHES: dict[str, tuple[str, ...]] = {
    ".pdf": (".pdf",),
    ".docx": (".docx", ".zip"),  # OOXML is a zip container
    ".xlsx": (".xlsx", ".zip"),
    ".png": (".png",),
    ".jpg": (".jpg", ".jpeg", ".jfif"),
    ".jpeg": (".jpg", ".jpeg", ".jfif"),
    ".webp": (".webp", ".riff"),
}


def _build_parsers() -> dict[str, Parser]:
    # NOTE (Task 2): only the text parser exists yet. Task 3 Step 8b extends this
    # with PdfParser/DocxParser/XlsxParser/ImageParser once those modules exist.
    text = TextParser()
    return {
        ".txt": text,
        ".md": text,
    }


_parsers: dict[str, Parser] | None = None


def get_parser(extension: str, default: Parser | None = None) -> Parser | None:
    global _parsers
    if _parsers is None:
        _parsers = _build_parsers()
    return _parsers.get(extension.lower(), default)


def _detected_extensions(data: bytes) -> set[str]:
    try:
        return {m.extension.lower() for m in puremagic.magic_string(data) if m.extension}
    except puremagic.PuremagicException:
        return set()


def sniff_matches_extension(data: bytes, extension: str) -> bool:
    """Byte-signature check: the content must be plausible for the extension.

    Binary formats must positively match their signature family. Plain-text
    formats pass as long as the bytes don't match some OTHER known binary type.
    """
    detected = _detected_extensions(data)
    expected = _BINARY_EXT_MATCHES.get(extension.lower())
    if expected is not None:
        return any(d in expected for d in detected)
    # txt/md: reject if the content is recognizably one of our binary formats
    all_binary = {ext for exts in _BINARY_EXT_MATCHES.values() for ext in exts}
    return not (detected & all_binary)
```

NOTE for Task 2: `SUPPORTED_TYPES` already lists all nine extensions (it's pure metadata used by the router and tests), but `_build_parsers()` only maps `.txt`/`.md` until Task 3 adds the heavy parsers. `get_parser(".pdf")` returns None during Task 2 — nothing calls it until Task 3's tests.

- [ ] **Step 7: Run tests, lint, commit**

Run: `uv run pytest tests/test_ingestion_parsers.py -v` → all PASS (the pdf/docx/xlsx/image parser tests come in Task 3).
Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check .` → 48 + new tests green.

```bash
git add app/ingestion/ tests/test_ingestion_parsers.py
git commit -m "feat: ingestion core - parsed-document types, text parser, chunking, registry"
```

---

### Task 3: Format parsers — PDF (+OCR detection), DOCX, XLSX, images + vision module

**Files:**
- Create: `app/ingestion/pdf_parser.py`, `app/ingestion/docx_parser.py`, `app/ingestion/xlsx_parser.py`, `app/ingestion/image_parser.py`, `app/ingestion/vision.py`
- Modify: `app/shared/llm.py`, `app/shared/config.py`, `tests/test_ingestion_parsers.py` (append), `tests/conftest.py` (fake vision fixture)

- [ ] **Step 1: Write the failing tests** (append to `tests/test_ingestion_parsers.py`)

```python
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


# --- image parser (vision is faked by the autouse conftest fixture) ---


async def test_image_parser_uses_vision() -> None:
    parser = get_parser(".png")
    data = (FIXTURES / "sample.png").read_bytes()
    parsed = parser.parse(data, "sample.png")
    # Image parsing defers extraction: it flags a single pseudo-page for OCR
    assert parsed.page_count == 1
    assert parsed.needs_ocr_pages == [1]
    assert parsed.blocks == []
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_ingestion_parsers.py -v`
Expected: new tests FAIL (`get_parser(".pdf")` raises ImportError from `_build_parsers` — modules missing).

- [ ] **Step 3: Config + vision model**

In `app/shared/config.py`, after `MAX_UPLOAD_BYTES` add:

```python
    VISION_MODEL: str = "gpt-4o-mini"

    MAX_PDF_PAGES: int = 50
    MAX_OCR_PAGES_PER_DOC: int = 20
    MAX_DOCS_PER_SESSION: int = 20
    MAX_CHUNKS_PER_DOC: int = 500
```

In `app/shared/llm.py`, add (module global `_vision_model: BaseChatModel | None = None` next to `_chat_model`):

```python
_vision_model: BaseChatModel | None = None


def get_vision_model() -> BaseChatModel:
    """Multimodal model used for OCR of scanned pages and images."""
    global _vision_model
    if _vision_model is None:
        settings = get_settings()
        _vision_model = ChatOpenAI(
            model=settings.VISION_MODEL,
            api_key=settings.OPENAI_API_KEY,
            temperature=0,
        )
    return _vision_model
```

- [ ] **Step 4: Implement `app/ingestion/vision.py`**

```python
from __future__ import annotations

import base64
import logging

from langchain_core.messages import HumanMessage

from app.shared.llm import get_vision_model

logger = logging.getLogger(__name__)

VISION_PROMPT = (
    "Transcribe ALL text visible in this document page image, verbatim. "
    "Preserve the reading order and structure using markdown (headings, lists, "
    "tables). If the page contains charts or figures, describe them briefly in "
    "[brackets]. Return ONLY the transcription, no commentary."
)


async def extract_text_from_image(png_bytes: bytes) -> str:
    """OCR a single page/image via the vision LLM. Returns extracted text."""
    encoded = base64.b64encode(png_bytes).decode()
    message = HumanMessage(
        content=[
            {"type": "text", "text": VISION_PROMPT},
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{encoded}"},
            },
        ]
    )
    response = await get_vision_model().ainvoke([message])
    return response.content if isinstance(response.content, str) else str(response.content)


def rasterize_pdf_page(pdf_bytes: bytes, page_index: int, scale: float = 2.0) -> bytes:
    """Render one PDF page (0-based index) to PNG bytes via pypdfium2.

    Pages are rendered one at a time so memory stays bounded on small instances.
    """
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(pdf_bytes)
    try:
        page = pdf[page_index]
        bitmap = page.render(scale=scale)
        pil_image = bitmap.to_pil()
        from io import BytesIO

        buf = BytesIO()
        pil_image.save(buf, format="PNG")
        return buf.getvalue()
    finally:
        pdf.close()
```

NOTE: `bitmap.to_pil()` requires Pillow, which pypdfium2 pulls in via its `to_pil` helper — verify; if Pillow isn't a transitive dep, add `"pillow>=10.0.0"` to prod dependencies (it almost certainly is needed — check `uv pip list`).

- [ ] **Step 5: Implement `app/ingestion/pdf_parser.py`**

```python
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
            except Exception:  # pypdf raises varied internals; a bad page must not kill the doc
                text = ""
            if len(text) >= MIN_TEXT_CHARS:
                blocks.append(ParsedBlock(text=text, page_number=i))
            else:
                needs_ocr.append(i)

        return ParsedDocument(
            blocks=blocks, page_count=page_count, needs_ocr_pages=needs_ocr
        )
```

- [ ] **Step 6: Implement `app/ingestion/docx_parser.py`**

```python
from __future__ import annotations

from io import BytesIO

import docx

from app.ingestion.base import ParsedBlock, ParsedDocument
from app.shared.errors import ParseFailedError


def _table_to_markdown(table) -> str:
    rows = [[cell.text.strip() for cell in row.cells] for row in table.rows]
    if not rows:
        return ""
    lines = ["| " + " | ".join(rows[0]) + " |"]
    lines.append("|" + "---|" * len(rows[0]))
    for row in rows[1:]:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


class DocxParser:
    def parse(self, data: bytes, filename: str) -> ParsedDocument:
        try:
            document = docx.Document(BytesIO(data))
        except Exception as exc:
            raise ParseFailedError("Could not read the Word document") from exc

        parts: list[str] = []
        for paragraph in document.paragraphs:
            if paragraph.text.strip():
                parts.append(paragraph.text.strip())
        for table in document.tables:
            markdown = _table_to_markdown(table)
            if markdown:
                parts.append(markdown)

        if not parts:
            raise ParseFailedError("The Word document contains no text")

        return ParsedDocument(blocks=[ParsedBlock(text="\n\n".join(parts))])
```

- [ ] **Step 7: Implement `app/ingestion/xlsx_parser.py`**

```python
from __future__ import annotations

from io import BytesIO

from openpyxl import load_workbook

from app.ingestion.base import ParsedBlock, ParsedDocument
from app.shared.errors import ParseFailedError

MAX_SHEETS = 10
MAX_ROWS_PER_SHEET = 2000
ROWS_PER_BLOCK = 30


def _markdown_row(values: tuple) -> str:
    cells = ["" if v is None else str(v) for v in values]
    return "| " + " | ".join(cells) + " |"


class XlsxParser:
    def parse(self, data: bytes, filename: str) -> ParsedDocument:
        try:
            workbook = load_workbook(BytesIO(data), read_only=True, data_only=True)
        except Exception as exc:
            raise ParseFailedError("Could not read the Excel file") from exc

        blocks: list[ParsedBlock] = []
        for sheet in workbook.worksheets[:MAX_SHEETS]:
            rows = sheet.iter_rows(values_only=True)
            header = next(rows, None)
            if header is None:
                continue
            header_md = _markdown_row(header)
            separator = "|" + "---|" * len(header)

            batch: list[str] = []
            row_count = 0
            for values in rows:
                if row_count >= MAX_ROWS_PER_SHEET:
                    break
                if all(v is None for v in values):
                    continue
                batch.append(_markdown_row(values))
                row_count += 1
                if len(batch) == ROWS_PER_BLOCK:
                    blocks.append(
                        ParsedBlock(
                            text="\n".join([header_md, separator, *batch]),
                            sheet_name=sheet.title,
                            is_atomic=True,
                        )
                    )
                    batch = []
            if batch:
                blocks.append(
                    ParsedBlock(
                        text="\n".join([header_md, separator, *batch]),
                        sheet_name=sheet.title,
                        is_atomic=True,
                    )
                )
        workbook.close()

        if not blocks:
            raise ParseFailedError("The Excel file contains no data")

        return ParsedDocument(blocks=blocks)
```

- [ ] **Step 8: Implement `app/ingestion/image_parser.py`**

```python
from __future__ import annotations

from app.ingestion.base import ParsedDocument


class ImageParser:
    """Images defer extraction to the OCR stage: one pseudo-page flagged for vision."""

    def parse(self, data: bytes, filename: str) -> ParsedDocument:
        return ParsedDocument(blocks=[], page_count=1, needs_ocr_pages=[1])
```

- [ ] **Step 8b: Register the new parsers.** In `app/ingestion/registry.py`, `_build_parsers` becomes:

```python
def _build_parsers() -> dict[str, Parser]:
    # Imported here (not module top) so importing the registry stays cheap.
    from app.ingestion.docx_parser import DocxParser
    from app.ingestion.image_parser import ImageParser
    from app.ingestion.pdf_parser import PdfParser
    from app.ingestion.xlsx_parser import XlsxParser

    text = TextParser()
    image = ImageParser()
    return {
        ".txt": text,
        ".md": text,
        ".pdf": PdfParser(),
        ".docx": DocxParser(),
        ".xlsx": XlsxParser(),
        ".png": image,
        ".jpg": image,
        ".jpeg": image,
        ".webp": image,
    }
```

- [ ] **Step 9: Add the fake-vision autouse fixture to `tests/conftest.py`**

```python
FAKE_VISION_TEXT = "Scanned page about photosynthesis and chlorophyll absorption."


@pytest.fixture(autouse=True)
def mock_vision(monkeypatch: pytest.MonkeyPatch) -> str:
    """Replace vision OCR with a canned transcription (no network).

    Yields the canned text so tests can assert against it without importing
    from conftest (tests/ is not a package).
    """
    import app.ingestion.vision as vision_module

    async def _fake_extract(png_bytes: bytes) -> str:
        return FAKE_VISION_TEXT

    def _fake_rasterize(pdf_bytes: bytes, page_index: int, scale: float = 2.0) -> bytes:
        return b"fake-png"

    monkeypatch.setattr(vision_module, "extract_text_from_image", _fake_extract)
    monkeypatch.setattr(vision_module, "rasterize_pdf_page", _fake_rasterize)
    yield FAKE_VISION_TEXT
```

IMPORTANT consequence for tests: any test that asserts on the OCR text takes `mock_vision` as a parameter and uses its yielded value — do NOT `from tests.conftest import FAKE_VISION_TEXT` (tests/ is not a package; that import fails).

IMPORTANT consequence for Task 4: `app/ingestion/service.py` must call these as `vision.extract_text_from_image(...)` / `vision.rasterize_pdf_page(...)` via `from app.ingestion import vision` — module-attribute access — so the monkeypatch bites.

- [ ] **Step 10: Run, lint, commit**

`uv run pytest tests/test_ingestion_parsers.py -v` → ALL PASS.
`uv run pytest -q && uv run ruff check . && uv run ruff format --check .` → green.

```bash
git add app/ingestion/ app/shared/llm.py app/shared/config.py tests/
git commit -m "feat: pdf/docx/xlsx/image parsers with OCR flagging + vision module"
```

---

### Task 4: Async ingestion pipeline — orchestrator, background tasks, router rework, reconciliation

**Files:**
- Create: `app/ingestion/service.py`, `tests/test_ingestion.py`
- Modify: `app/documents/router.py`, `app/documents/service.py`, `app/shared/errors.py`, `app/main.py`, `tests/test_documents.py`, `tests/test_search.py`, `tests/test_chat.py`, `scripts/streamlit_app.py` (allowed types only)

- [ ] **Step 1: Add the session-limit error** to `app/shared/errors.py`:

```python
class SessionLimitExceededError(AppError):
    code = "SESSION_DOCUMENT_LIMIT"
    status_code = 409
```

- [ ] **Step 2: Write the failing API tests.** Create `tests/test_ingestion.py`:

```python
from __future__ import annotations

import uuid
from pathlib import Path

import httpx
import pytest

from app.ingestion.service import wait_for_ingestion

FIXTURES = Path(__file__).parent / "fixtures"


async def _create_session(client: httpx.AsyncClient) -> str:
    response = await client.post("/sessions")
    assert response.status_code == 201
    return response.json()["id"]


async def _upload_fixture(
    client: httpx.AsyncClient, sid: str, name: str, mime: str
) -> dict:
    data = (FIXTURES / name).read_bytes()
    response = await client.post(
        f"/sessions/{sid}/documents",
        files={"file": (name, data, mime)},
    )
    assert response.status_code == 202, response.text
    return response.json()


async def _get_doc(client: httpx.AsyncClient, sid: str, doc_id: str) -> dict:
    docs = (await client.get(f"/sessions/{sid}/documents")).json()
    return next(d for d in docs if d["id"] == doc_id)


async def test_upload_returns_pending_then_processes(client: httpx.AsyncClient) -> None:
    sid = await _create_session(client)
    doc = await _upload_fixture(client, sid, "sample.pdf", "application/pdf")
    assert doc["status"] == "pending"
    assert doc["chunk_count"] == 0

    await wait_for_ingestion()

    final = await _get_doc(client, sid, doc["id"])
    assert final["status"] == "ready"
    assert final["page_count"] == 2
    assert final["chunk_count"] >= 1
    assert final["progress"] == 100


async def test_pdf_content_is_searchable(client: httpx.AsyncClient) -> None:
    sid = await _create_session(client)
    await _upload_fixture(client, sid, "sample.pdf", "application/pdf")
    await wait_for_ingestion()

    response = await client.get(
        "/search", params={"q": "photosynthesis light energy", "session_id": sid}
    )
    results = response.json()
    assert len(results) == 1
    assert results[0]["filename"] == "sample.pdf"


async def test_scanned_pdf_goes_through_ocr(
    client: httpx.AsyncClient, mock_vision: str
) -> None:
    sid = await _create_session(client)
    doc = await _upload_fixture(client, sid, "scanned.pdf", "application/pdf")
    await wait_for_ingestion()

    final = await _get_doc(client, sid, doc["id"])
    assert final["status"] == "ready"
    assert final["page_count"] == 2

    response = await client.get(
        "/search", params={"q": "photosynthesis", "session_id": sid}
    )
    results = response.json()
    assert results, "OCR text should be searchable"
    assert mock_vision.split()[0].lower() in results[0]["chunks"][0]["chunk_text"].lower()


async def test_docx_upload(client: httpx.AsyncClient) -> None:
    sid = await _create_session(client)
    doc = await _upload_fixture(
        client, sid, "sample.docx",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
    await wait_for_ingestion()
    final = await _get_doc(client, sid, doc["id"])
    assert final["status"] == "ready"
    assert final["chunk_count"] >= 1


async def test_xlsx_upload_produces_table_chunks(client: httpx.AsyncClient) -> None:
    sid = await _create_session(client)
    doc = await _upload_fixture(
        client, sid, "sample.xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    await wait_for_ingestion()
    final = await _get_doc(client, sid, doc["id"])
    assert final["status"] == "ready"

    response = await client.get("/search", params={"q": "grades", "session_id": sid})
    results = response.json()
    assert results
    assert "| Student | Subject | Grade |" in results[0]["chunks"][0]["chunk_text"]


async def test_image_upload_uses_vision(client: httpx.AsyncClient) -> None:
    sid = await _create_session(client)
    doc = await _upload_fixture(client, sid, "sample.png", "image/png")
    await wait_for_ingestion()
    final = await _get_doc(client, sid, doc["id"])
    assert final["status"] == "ready"
    assert final["page_count"] == 1
    assert final["chunk_count"] >= 1


async def test_mismatched_signature_rejected_at_upload(
    client: httpx.AsyncClient,
) -> None:
    sid = await _create_session(client)
    png_bytes = (FIXTURES / "sample.png").read_bytes()
    response = await client.post(
        f"/sessions/{sid}/documents",
        files={"file": ("fake.pdf", png_bytes, "application/pdf")},
    )
    assert response.status_code == 415
    assert response.json()["error"]["code"] == "UNSUPPORTED_FILE_TYPE"


async def test_corrupt_pdf_fails_async(client: httpx.AsyncClient) -> None:
    sid = await _create_session(client)
    # Valid %PDF signature so it passes the router sniff, but unreadable content
    response = await client.post(
        f"/sessions/{sid}/documents",
        files={"file": ("corrupt.pdf", b"%PDF-1.4 garbage", "application/pdf")},
    )
    assert response.status_code == 202
    doc = response.json()
    await wait_for_ingestion()

    final = await _get_doc(client, sid, doc["id"])
    assert final["status"] == "failed"
    assert final["error_code"] == "parse_failed"
    assert final["error_message"]


async def test_page_limit_fails_async(client: httpx.AsyncClient) -> None:
    from io import BytesIO

    from pypdf import PdfWriter

    writer = PdfWriter()
    for _ in range(51):
        writer.add_blank_page(width=200, height=200)
    buf = BytesIO()
    writer.write(buf)

    sid = await _create_session(client)
    response = await client.post(
        f"/sessions/{sid}/documents",
        files={"file": ("big.pdf", buf.getvalue(), "application/pdf")},
    )
    assert response.status_code == 202
    doc = response.json()
    await wait_for_ingestion()

    final = await _get_doc(client, sid, doc["id"])
    assert final["status"] == "failed"
    assert final["error_code"] == "page_limit_exceeded"


async def test_session_document_cap(client: httpx.AsyncClient) -> None:
    from app.shared.config import get_settings

    settings = get_settings()
    original = settings.MAX_DOCS_PER_SESSION
    settings.MAX_DOCS_PER_SESSION = 1
    try:
        sid = await _create_session(client)
        await _upload_fixture(client, sid, "sample.txt", "text/plain")
        await wait_for_ingestion()

        data = (FIXTURES / "sample.txt").read_bytes()
        response = await client.post(
            f"/sessions/{sid}/documents",
            files={"file": ("second.txt", data, "text/plain")},
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "SESSION_DOCUMENT_LIMIT"
    finally:
        settings.MAX_DOCS_PER_SESSION = original


async def test_ocr_page_cap_limits_vision_calls(client: httpx.AsyncClient) -> None:
    """Pages beyond MAX_OCR_PAGES_PER_DOC are skipped (logged), doc still ready."""
    from io import BytesIO

    from pypdf import PdfWriter

    from app.shared.config import get_settings

    settings = get_settings()
    original = settings.MAX_OCR_PAGES_PER_DOC
    settings.MAX_OCR_PAGES_PER_DOC = 1
    try:
        writer = PdfWriter()
        for _ in range(3):
            writer.add_blank_page(width=200, height=200)
        buf = BytesIO()
        writer.write(buf)

        sid = await _create_session(client)
        response = await client.post(
            f"/sessions/{sid}/documents",
            files={"file": ("scans.pdf", buf.getvalue(), "application/pdf")},
        )
        assert response.status_code == 202
        doc = response.json()
        await wait_for_ingestion()

        final = await _get_doc(client, sid, doc["id"])
        assert final["status"] == "ready"
        # Only 1 of 3 scanned pages was OCR'd -> exactly 1 page of chunks
        assert final["chunk_count"] >= 1
    finally:
        settings.MAX_OCR_PAGES_PER_DOC = original


async def test_unknown_extension_still_415(client: httpx.AsyncClient) -> None:
    sid = await _create_session(client)
    response = await client.post(
        f"/sessions/{sid}/documents",
        files={"file": ("malware.exe", b"MZ...", "application/octet-stream")},
    )
    assert response.status_code == 415
```

- [ ] **Step 3: Run to verify failure** — `uv run pytest tests/test_ingestion.py -v` → FAIL (no `app.ingestion.service`).

- [ ] **Step 4: Implement `app/ingestion/service.py`**

```python
from __future__ import annotations

import asyncio
import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.documents.models import Document, DocumentChunk, DocumentStatus
from app.ingestion import vision
from app.ingestion.base import ParsedBlock, ParsedDocument
from app.ingestion.chunking import build_enriched_text, chunk_blocks
from app.ingestion.registry import get_parser
from app.shared.config import get_settings
from app.shared.database import get_session_factory
from app.shared.embeddings import get_embedding_provider
from app.shared.errors import AppError, ParseFailedError

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}

logger = logging.getLogger(__name__)

# Strong references to in-flight tasks (asyncio only keeps weak ones).
_tasks: set[asyncio.Task] = set()


def schedule_processing(document_id: uuid.UUID, data: bytes, extension: str) -> None:
    """Fire-and-forget background processing; the upload endpoint returns 202."""
    task = asyncio.create_task(process_document(document_id, data, extension))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


async def wait_for_ingestion() -> None:
    """Test helper: wait until every scheduled ingestion task has finished."""
    while _tasks:
        await asyncio.gather(*list(_tasks), return_exceptions=True)


async def process_document(
    document_id: uuid.UUID, data: bytes, extension: str
) -> None:
    """Parse -> OCR -> chunk -> embed -> save, updating status/stage/progress.

    Opens its own DB session (the request session is gone by the time this runs).
    Every stage transition commits so the polling endpoint sees progress.
    """
    factory = get_session_factory()
    async with factory() as db:
        document = await db.get(Document, document_id)
        if document is None:  # deleted before processing started
            return
        try:
            settings = get_settings()

            # --- parse ---
            await _set_stage(db, document, "parsing", progress=5)
            parser = get_parser(extension)
            if parser is None:  # defensive; router already validated
                raise ParseFailedError(f"No parser for {extension}")
            parsed: ParsedDocument = parser.parse(data, document.filename)

            # --- ocr ---
            if parsed.needs_ocr_pages:
                await _set_stage(db, document, "ocr", progress=10)
                ocr_pages = parsed.needs_ocr_pages[: settings.MAX_OCR_PAGES_PER_DOC]
                skipped = len(parsed.needs_ocr_pages) - len(ocr_pages)
                if skipped:
                    logger.warning(
                        "Document %s: skipping OCR for %d pages beyond the cap",
                        document.id,
                        skipped,
                    )
                for n, page_number in enumerate(ocr_pages, start=1):
                    if extension in IMAGE_EXTENSIONS:
                        png = data  # the upload IS the image
                    else:
                        png = vision.rasterize_pdf_page(data, page_number - 1)
                    text = await vision.extract_text_from_image(png)
                    if text.strip():
                        # OCR output joins the regular blocks with its page number
                        parsed.blocks.append(
                            ParsedBlock(text=text, page_number=page_number)
                        )
                    progress = 10 + int(40 * n / len(ocr_pages))
                    await _set_stage(db, document, "ocr", progress=progress)

            # --- chunk ---
            chunks = chunk_blocks(parsed.blocks, max_chunks=settings.MAX_CHUNKS_PER_DOC)
            if not chunks:
                raise ParseFailedError("No text could be extracted from the document")

            # --- embed ---
            await _set_stage(db, document, "embedding", progress=60)
            enriched = [
                build_enriched_text(
                    document.filename, c.text, c.page_number, c.sheet_name
                )
                for c in chunks
            ]
            embeddings = await get_embedding_provider().embed_batch(enriched)

            # --- save ---
            await _set_stage(db, document, "saving", progress=90)
            db.add_all(
                [
                    DocumentChunk(
                        document_id=document.id,
                        chunk_index=i,
                        page_number=chunk.page_number,
                        chunk_text=chunk.text,
                        embedding=embedding,
                    )
                    for i, (chunk, embedding) in enumerate(
                        zip(chunks, embeddings, strict=True)
                    )
                ]
            )
            document.page_count = parsed.page_count
            document.chunk_count = len(chunks)
            document.status = DocumentStatus.READY
            document.stage = None
            document.progress = 100
            db.add(document)
            await db.commit()
        except Exception as exc:
            logger.exception("Failed to process document %s", document_id)
            await db.rollback()
            if isinstance(exc, AppError):
                document.error_code = exc.code.lower()
                document.error_message = exc.message
            else:
                document.error_code = "processing_failed"
                document.error_message = "Failed to process the document."
            document.status = DocumentStatus.FAILED
            document.stage = None
            try:
                db.add(document)
                await db.commit()
            except Exception:
                logger.exception(
                    "Could not persist FAILED status for document %s", document_id
                )


async def _set_stage(
    db: AsyncSession, document: Document, stage: str, progress: int
) -> None:
    document.status = DocumentStatus.PROCESSING
    document.stage = stage
    document.progress = progress
    db.add(document)
    await db.commit()
```

NOTE: `error_code` for AppError failures is the lowercase of the subclass code (e.g. `parse_failed`, `page_limit_exceeded`), matching the test assertions in Step 2.

- [ ] **Step 5: Rework `app/documents/router.py` upload endpoint**

Replace `TEXT_EXTENSIONS` usage with the registry. The new upload handler:

```python
from app.documents.service import (
    count_documents,
    create_pending_document,
    delete_document,
    list_documents,
)
from app.ingestion.registry import SUPPORTED_TYPES, sniff_matches_extension
from app.ingestion.service import schedule_processing
from app.shared.errors import (
    FileTooLargeError,
    SessionLimitExceededError,
    UnsupportedFileTypeError,
)


@router.post("", response_model=DocumentResponse, status_code=status.HTTP_202_ACCEPTED)
async def upload_document(
    session_id: uuid.UUID,
    file: UploadFile,
    db: AsyncSession = Depends(get_session),
) -> DocumentResponse:
    session = await get_active_session(db, session_id)
    settings = get_settings()

    if await count_documents(db, session_id) >= settings.MAX_DOCS_PER_SESSION:
        raise SessionLimitExceededError(
            f"This session already has {settings.MAX_DOCS_PER_SESSION} documents"
        )

    filename = file.filename or "upload"
    ext = _extension(filename)
    if ext not in SUPPORTED_TYPES:
        supported = ", ".join(sorted(SUPPORTED_TYPES))
        raise UnsupportedFileTypeError(
            f"Unsupported file type '{ext or filename}'. Supported: {supported}"
        )

    data = await file.read(settings.MAX_UPLOAD_BYTES + 1)
    if len(data) > settings.MAX_UPLOAD_BYTES:
        limit_mb = settings.MAX_UPLOAD_BYTES // (1024 * 1024)
        raise FileTooLargeError(f"File exceeds the {limit_mb} MB limit")

    if not sniff_matches_extension(data, ext):
        raise UnsupportedFileTypeError(
            f"File content does not match the '{ext}' extension"
        )

    document = await create_pending_document(
        db,
        session_id=session_id,
        filename=filename,
        mime_type=SUPPORTED_TYPES[ext],
        size_bytes=len(data),
    )
    await touch_session(db, session)
    schedule_processing(document.id, data, ext)
    return DocumentResponse.model_validate(document, from_attributes=True)
```

(`ParseFailedError` import is no longer needed in the router — decode/empty checks moved into TextParser. The GET/DELETE endpoints are unchanged.)

- [ ] **Step 6: Slim `app/documents/service.py`**

Delete `process_text_document`, the module-level `_splitter`, and `build_enriched_text` (now in `app/ingestion/chunking.py`). Add:

```python
from sqlalchemy import func, select


async def count_documents(db: AsyncSession, session_id: uuid.UUID) -> int:
    result = await db.execute(
        select(func.count())
        .select_from(Document)
        .where(Document.session_id == session_id)
    )
    return int(result.scalar_one())
```

Keep `create_pending_document`, `list_documents`, `delete_document`. Remove now-unused imports (`RecursiveCharacterTextSplitter`, `get_embedding_provider`, `DocumentChunk` if unused, `logging` if unused).

- [ ] **Step 7: Startup reconciliation in `app/main.py` lifespan**

After `create_all`, add:

```python
    from sqlalchemy import update

    from app.documents.models import DocumentStatus

    async with get_engine().begin() as conn:
        await conn.execute(
            update(Document)
            .where(Document.status.in_([DocumentStatus.PENDING, DocumentStatus.PROCESSING]))
            .values(
                status=DocumentStatus.FAILED,
                stage=None,
                error_code="interrupted",
                error_message="Processing was interrupted by a server restart.",
            )
        )
```

(Place imports at the top of the file, not inline. `Document` is already imported.)

- [ ] **Step 8: Adapt existing tests to the async contract**

`tests/test_documents.py`:
- Add `from app.ingestion.service import wait_for_ingestion` and a small helper `async def _await_ready(client, sid, doc_id) -> dict` that calls `wait_for_ingestion()` then fetches the doc.
- `test_upload_markdown_document`: assert 202 + `status == "pending"`; then `await wait_for_ingestion()`; re-fetch via list; assert ready + chunk_count ≥ 1.
- `test_upload_txt_document`: same pattern.
- `test_upload_invalid_utf8_returns_422` → RENAME to `test_upload_invalid_utf8_fails_async`: 202, await, status failed, error_code "parse_failed".
- `test_upload_empty_file_returns_422` → `test_upload_empty_file_fails_async`: same pattern.
- `test_upload_unsupported_type_returns_415`, oversized 413, unknown-session 404: unchanged (still synchronous router rejections).
- `test_processing_failure_marks_document_failed` / `test_search_excludes_failed_documents`: add `await wait_for_ingestion()` after upload before asserting; response no longer carries final status — fetch from the list endpoint.
- `test_list_documents`, `test_delete_document`, etc.: add `await wait_for_ingestion()` after uploads.
- `test_session_detail_includes_documents`: await ingestion first.

`tests/test_search.py`: in `_upload_md`, after the 202 assert, replace `assert response.json()["status"] == "ready"` with `await wait_for_ingestion()` (import the helper).

`tests/test_chat.py`: in the `chat_session` fixture, after the upload loop add `await wait_for_ingestion()` (import the helper).

`scripts/streamlit_app.py`: change `type=["txt", "md"]` to `type=["txt", "md", "pdf", "docx", "xlsx", "png", "jpg", "jpeg", "webp"]` and the label to "Upload a document". (The doc list already renders pending/processing with ⏳; add `st.button("🔄 Refresh")` under the Documents header so a dev can poll manually: `if st.button("🔄 Refresh"): st.rerun()`.)

- [ ] **Step 9: Run everything**

`uv run pytest -q` → ALL green (existing 48 adapted + ~12 parser unit tests + ~12 ingestion API tests).
`uv run ruff check . && uv run ruff format --check .` → clean.

- [ ] **Step 10: Manual smoke test with a REAL pdf and REAL vision call**

Requires `OPENAI_API_KEY` in `.env`. Start the API, then upload `tests/fixtures/sample.pdf` and `tests/fixtures/scanned.pdf` via curl to a fresh session; poll `GET /sessions/{id}/documents` until ready; confirm `page_count`, OCR text searchable for the scanned one. Watch logs for the vision call. Kill the server after. (If no key available, note it and rely on the suite.)

- [ ] **Step 11: Commit**

```bash
git add -A
git commit -m "feat!: async ingestion pipeline with parser registry and vision OCR

Uploads return 202+pending; a background task parses (pdf/docx/xlsx/images/
txt/md), OCRs scanned pages via vision LLM, chunks, embeds, and updates
status/stage/progress. Parse failures surface uniformly as failed documents.
Startup reconciliation marks orphaned rows failed/interrupted."
```

---

## Verification (end of Phase 2)

1. `uv run pytest -q` green; `uv run ruff check .` + `ruff format --check .` clean.
2. Manual: upload each fixture type via Streamlit dev tool; watch status pending → processing(stage/progress) → ready; failed cases (corrupt pdf renamed, oversized, .exe) produce clean envelopes or failed rows.
3. Real-key smoke: scanned.pdf OCR'd by actual gpt-4o-mini; content searchable; chat cites [scanned.pdf].
4. Restart the API mid-ingestion of a large PDF → row becomes failed/interrupted (startup reconciliation).

## Out of scope (later phases)

- TTL sweeper, rate limiting, tenacity retries on vision/embeddings → Phase 3
- Guardrails → Phase 4; Langfuse on vision calls → Phase 5; frontend → Phase 6.
