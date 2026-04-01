"""
Job level classifier.

Buckets a job into one of:
  APM | PM | Senior PM | Staff PM | Principal PM | Group PM
  Director | VP | CPO | TPM | Unknown

Strategy:
  1. Try to match the raw title against ordered regex patterns (most-specific first).
  2. If no title match, scan the first 400 chars of the description for level signals.
"""
import re
from typing import Optional

# Each entry: (level_label, list_of_title_patterns)
# Patterns are tried in order; first match wins.
_TITLE_RULES: list[tuple[str, list[str]]] = [
    ("CPO",          [r"\bcpo\b", r"chief product officer"]),
    ("VP",           [r"\bvp\b.*product", r"vice president.*product", r"product.*vice president"]),
    ("Director",     [r"director.*product", r"product.*director"]),
    ("Group PM",     [r"group product manager", r"\bgpm\b"]),
    ("Principal PM", [r"principal product manager", r"principal pm"]),
    ("Staff PM",     [r"staff product manager", r"staff pm"]),
    ("Senior PM",    [r"senior product manager", r"senior pm", r"sr\.?\s*product manager", r"sr\.?\s*pm\b"]),
    ("TPM",          [r"\btpm\b", r"technical program manager", r"technical product manager"]),
    ("APM",          [r"\bapm\b", r"associate product manager", r"associate pm"]),
    # Catch-all PM — must come after all specialisations
    ("PM",           [r"product manager", r"\bpm\b"]),
]

# Description-level fallback signals
_DESC_SIGNALS: list[tuple[str, list[str]]] = [
    ("VP",           [r"vp of product", r"vice president of product"]),
    ("Director",     [r"director of product", r"head of product"]),
    ("Senior PM",    [r"5\+\s*years", r"7\+\s*years", r"senior.*product"]),
    ("APM",          [r"0[–-]2\s*years", r"new grad", r"associate product"]),
    ("TPM",          [r"technical program", r"engineering.*product"]),
]


def _match_patterns(text: str, patterns: list[str]) -> bool:
    lowered = text.lower()
    for p in patterns:
        if re.search(p, lowered):
            return True
    return False


def classify_level(title: str, description: Optional[str] = None) -> str:
    """Return the best-fit level label for a job."""
    title = title or ""

    for level, patterns in _TITLE_RULES:
        if _match_patterns(title, patterns):
            return level

    # Fallback: scan first 400 chars of description
    if description:
        snippet = description[:400]
        for level, patterns in _DESC_SIGNALS:
            if _match_patterns(snippet, patterns):
                return level

    return "PM"  # safe default for product roles
