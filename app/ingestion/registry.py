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
#
# NOTE: signature sniffing is a *plausibility* gate, not validation.
# Any valid zip container will pass as .docx/.xlsx; the parsers must treat
# garbage zips as ParseFailedError rather than relying on sniff alone.
_BINARY_EXT_MATCHES: dict[str, tuple[str, ...]] = {
    ".pdf": (".pdf",),
    ".docx": (".docx", ".zip"),  # OOXML is a zip container
    ".xlsx": (".xlsx", ".zip"),
    ".png": (".png",),
    ".jpg": (".jpg", ".jpeg", ".jfif"),
    ".jpeg": (".jpg", ".jpeg", ".jfif"),
    ".webp": (".webp",),  # .riff dropped: any RIFF container (wav/avi) would also pass
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
    if not data:
        return set()
    try:
        return {
            m.extension.lower() for m in puremagic.magic_string(data) if m.extension
        }
    except (puremagic.PureError, ValueError):
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
