"""Narrow server-side sensitive content detection for prompts, letter bodies, and notes.

Enforces Item E of the participant privacy and production-readiness roadmap:
- Deterministic, zero-external-API pattern matching.
- Detects PII (phone numbers, email addresses, SSN/card patterns) and spam links.
- Detects prohibited harassment / hate patterns.
- Preserves the exact submitted text without mangling or logging private content.
- Returns (is_restricted, reason). Flagged content is held for staff moderation.
"""
import re

# PII Patterns
PHONE_PATTERN = re.compile(r"\b(?:\+?1[-.\s]?)?\(?[0-9]{3}\)?[-.\s]?[0-9]{3}[-.\s]?[0-9]{4}\b")
EMAIL_PATTERN = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
SSN_PATTERN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
CARD_PATTERN = re.compile(r"\b(?:\d{4}[-\s]?){4}\b")

# Spam / external links
URL_PATTERN = re.compile(r"\bhttps?://[^\s]+\b|\bwww\.[a-zA-Z0-9-]+\.[a-zA-Z]{2,}\b", re.IGNORECASE)

# Offensive / harassment keywords (narrow, lowercase)
BLOCKED_TERMS = {
    "kill yourself",
    "kys",
    "doxx",
    "swatting",
    "bomb threat",
}


def screen_content(text: str) -> tuple[bool, str]:
    """Screen text for sensitive patterns.

    Returns:
        (True, reason) if content should be automatically restricted for review.
        (False, "") if content passes automated checks cleanly.
    """
    if not text or not isinstance(text, str):
        return False, ""

    text_lower = text.lower()

    # 1. Prohibited harassment / threat terms
    for term in BLOCKED_TERMS:
        if term in text_lower:
            return True, "prohibited_content_flagged"

    # 2. PII detection (phone numbers, SSNs, credit cards, emails)
    if SSN_PATTERN.search(text):
        return True, "ssn_pattern_detected"
    if CARD_PATTERN.search(text):
        return True, "card_pattern_detected"
    if PHONE_PATTERN.search(text):
        return True, "phone_pattern_detected"
    if EMAIL_PATTERN.search(text):
        return True, "email_pattern_detected"

    # 3. External links / spam detection
    if URL_PATTERN.search(text):
        return True, "external_link_flagged"

    return False, ""
