from __future__ import annotations

import base64
import logging
from io import BytesIO

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
    return (
        response.content if isinstance(response.content, str) else str(response.content)
    )


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
        buf = BytesIO()
        pil_image.save(buf, format="PNG")
        return buf.getvalue()
    finally:
        pdf.close()
