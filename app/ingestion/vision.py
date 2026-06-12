from __future__ import annotations

import base64
import logging
from io import BytesIO

from langchain_core.messages import HumanMessage

from app.shared.llm import get_vision_model
from app.shared.observability import get_langfuse_handler

logger = logging.getLogger(__name__)

VISION_PROMPT = (
    "Transcribe ALL text visible in this document page image, verbatim. "
    "Preserve the reading order and structure using markdown (headings, lists, "
    "tables). If the page contains charts or figures, describe them briefly in "
    "[brackets]. Return ONLY the transcription, no commentary. "
    "If the page contains no readable text at all, respond with exactly NO_TEXT."
)

_NON_TRANSCRIPTIONS = (
    "no_text",
    "i'm sorry",
    "i am sorry",
    "i can't",
    "i cannot",
)


def clean_transcription(text: str) -> str:
    """Return the transcription, or '' when the model produced no usable text.

    Vision models answer NO_TEXT per the prompt contract for blank pages, but
    may also refuse outright; either way the output must not enter the index.
    """
    stripped = text.strip()
    normalized = stripped.strip("[]() ").lower()
    if normalized.startswith(_NON_TRANSCRIPTIONS):
        return ""
    return stripped


async def extract_text_from_image(
    image_bytes: bytes,
    mime: str = "image/png",
    *,
    trace_metadata: dict | None = None,
) -> str:
    """OCR a single page/image via the vision LLM. Returns extracted text.

    The optional ``trace_metadata`` dict is forwarded to the Langfuse callback
    handler (when configured) so each OCR call appears as a traced span with
    document/page context. When no Langfuse keys are set the parameter is a
    strict no-op.
    """
    encoded = base64.b64encode(image_bytes).decode()
    message = HumanMessage(
        content=[
            {"type": "text", "text": VISION_PROMPT},
            {
                "type": "image_url",
                "image_url": {"url": f"data:{mime};base64,{encoded}"},
            },
        ]
    )
    handler = get_langfuse_handler()
    config: dict = {}
    if handler is not None:
        config = {
            "callbacks": [handler],
            "metadata": {"langfuse_tags": ["ocr"], **(trace_metadata or {})},
        }
    response = await get_vision_model().ainvoke([message], config=config or None)
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
