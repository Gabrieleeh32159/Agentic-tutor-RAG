from __future__ import annotations

import zipfile
from io import BytesIO

from app.shared.errors import ParseFailedError

MAX_DECOMPRESSED_BYTES = 100 * 1024 * 1024  # 100 MB


def check_zip_bomb(data: bytes, max_bytes: int | None = None) -> None:
    """Raise ParseFailedError if the zip decompresses beyond the byte limit.

    Call before handing bytes to python-docx / openpyxl so a malicious zip
    (docx/xlsx container) cannot trigger a decompression bomb.

    Args:
        data: Raw bytes of the Office document (zip container).
        max_bytes: Override the module-level cap (useful in tests).
    """
    limit = max_bytes if max_bytes is not None else MAX_DECOMPRESSED_BYTES
    try:
        with zipfile.ZipFile(BytesIO(data)) as zf:
            total = sum(info.file_size for info in zf.infolist())
    except zipfile.BadZipFile as exc:
        raise ParseFailedError("File is not a valid Office document") from exc
    if total > limit:
        raise ParseFailedError("Office document decompresses too large")
