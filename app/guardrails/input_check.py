from __future__ import annotations

import logging
import re

from app.guardrails import moderation
from app.shared.errors import GuardrailBlockedError

logger = logging.getLogger(__name__)

# High-precision prompt-injection markers. Deliberately conservative: false
# positives block legitimate questions, so each pattern targets phrasing that
# has no plausible use in a question about one's own documents.
_INJECTION_PATTERNS = [
    re.compile(
        r"ignore\s+(all\s+|any\s+)?(previous|prior|above|earlier)\s+(instructions|prompts|messages|rules)",
        re.IGNORECASE,
    ),
    re.compile(
        r"disregard\s+(all\s+)?(your|the|previous|prior)?\s*(system\s+)?(prompt|instructions|rules)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(reveal|print|show|output|repeat)\s+(me\s+)?(your|the)\s+(system\s+)?(prompt|instructions)",
        re.IGNORECASE,
    ),
    re.compile(
        r"you\s+are\s+now\s+(dan|unrestricted|jailbroken|free\s+of)", re.IGNORECASE
    ),
    re.compile(r"\bjailbreak\b", re.IGNORECASE),
]


def scan_for_injection(text: str) -> bool:
    return any(pattern.search(text) for pattern in _INJECTION_PATTERNS)


async def check_input(question: str) -> None:
    """Pre-stream input gate. Raises GuardrailBlockedError on injection or
    flagged content. Moderation outages fail OPEN (logged) - the local
    injection scan never degrades."""
    if scan_for_injection(question):
        raise GuardrailBlockedError(
            "This question looks like a prompt-injection attempt and was blocked."
        )

    try:
        result = await moderation.moderate_text(question)
    except Exception:
        logger.warning("Moderation unavailable; failing open", exc_info=True)
        return
    if result.flagged:
        categories = ", ".join(result.categories) or "policy violation"
        raise GuardrailBlockedError(
            f"This question was flagged by content moderation ({categories})."
        )
