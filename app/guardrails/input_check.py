from __future__ import annotations

# NOTE: This scan is English-only and heuristic. It targets the highest-signal
# injection phrases with a very low false-positive budget. Moderation, prompt
# hardening (system-prompt delimiters), and <retrieved-content> tags are the
# primary backstops; this is an early, cheap trip-wire.
import logging
import re
from dataclasses import dataclass

from app.guardrails import moderation
from app.shared.errors import GuardrailBlockedError

logger = logging.getLogger(__name__)


@dataclass
class InputCheckResult:
    moderation_degraded: bool = False


# High-precision prompt-injection markers. Deliberately conservative: false
# positives block legitimate questions, so each pattern targets phrasing that
# has no plausible use in a question about one's own documents.
_INJECTION_PATTERNS = [
    # Pattern 1: "ignore previous/prior/above/earlier instructions" — no
    # legitimate document question uses this phrasing.
    re.compile(
        r"ignore\s+(all\s+|any\s+)?(previous|prior|above|earlier)\s+(instructions|prompts|messages|rules)",
        re.IGNORECASE,
    ),
    # Pattern 2: "disregard <your|the> system prompt/instructions/rules" — bare
    # "disregard the rules in section 2" must NOT match; only fire when the
    # object is the system prompt / YOUR instructions / rules.
    re.compile(
        r"disregard\s+(all\s+)?(your\s+(system\s+)?(prompt|instructions|rules)|the\s+system\s+prompt)",
        re.IGNORECASE,
    ),
    # Pattern 3: reveal/print/show/output/repeat <your|the system> prompt/instructions
    # — "Print the instructions section of the manual" must NOT match; only
    # fire when "your" or "the system" precedes prompt/instructions.
    re.compile(
        r"(reveal|print|show|output|repeat)\s+(me\s+)?(your\s+(system\s+)?(prompt|instructions)|the\s+system\s+prompt)",
        re.IGNORECASE,
    ),
    re.compile(
        r"you\s+are\s+now\s+(dan|unrestricted|jailbroken|free\s+of)", re.IGNORECASE
    ),
    re.compile(r"\bjailbreak\b", re.IGNORECASE),
]


def scan_for_injection(text: str) -> bool:
    return any(pattern.search(text) for pattern in _INJECTION_PATTERNS)


async def check_input(question: str) -> InputCheckResult:
    """Pre-stream input gate. Raises GuardrailBlockedError on injection or
    flagged content. Moderation outages fail OPEN (logged) — the local
    injection scan never degrades. Returns InputCheckResult so callers can
    observe degradation signals (consumed by observability in Phase 5)."""
    if scan_for_injection(question):
        raise GuardrailBlockedError(
            "This question looks like a prompt-injection attempt and was blocked."
        )

    try:
        result = await moderation.moderate_text(question)
    except Exception:
        logger.warning("Moderation unavailable; failing open", exc_info=True)
        return InputCheckResult(moderation_degraded=True)
    if result.flagged:
        categories = ", ".join(result.categories) or "policy violation"
        raise GuardrailBlockedError(
            f"This question was flagged by content moderation ({categories})."
        )
    return InputCheckResult()
