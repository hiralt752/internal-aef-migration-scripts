"""Repair reversible Windows-1252/UTF-8 mojibake in question payloads."""

import re
from typing import Any, Optional


_MOJIBAKE_MARKERS = frozenset({
    "\u00c2",  # Â
    "\u00c3",  # Ã
    "\u00d8",  # Ø
    "\u00d9",  # Ù
    "\ufffd",  # replacement character
})

_C1_CONTROLS = frozenset(chr(value) for value in range(0x80, 0xA0))
_MOJIBAKE_MARKERS = _MOJIBAKE_MARKERS | frozenset({"\u00e2"})
_IMG_TAG_PATTERN = re.compile(r"(<img\b[^>]*>)", flags=re.IGNORECASE)


def _build_cp1252_reverse_map() -> dict[str, int]:
    """Map Windows-1252 characters back to their original byte values."""
    reverse: dict[str, int] = {}

    for value in range(256):
        try:
            character = bytes([value]).decode("cp1252")
        except UnicodeDecodeError:
            # Python leaves five Windows-1252 byte positions undefined. They
            # can still occur as C1 controls in historical mojibake strings.
            character = chr(value)

        reverse[character] = value

    for value in range(0x80, 0xA0):
        reverse.setdefault(chr(value), value)

    return reverse


_CP1252_REVERSE = _build_cp1252_reverse_map()
_CP1252_HIGH_CHARS = "".join(
    character
    for character, value in _CP1252_REVERSE.items()
    if value >= 0x80
)
_SUSPICIOUS_RUN_MARKERS = "".join(
    character for character in _MOJIBAKE_MARKERS if character != "\ufffd"
)
_SUSPICIOUS_RUN_PATTERN = re.compile(
    rf"[{re.escape(_SUSPICIOUS_RUN_MARKERS)}]"
    rf"[{re.escape(_CP1252_HIGH_CHARS)}]*"
)


def _mojibake_score(text: str) -> int:
    return sum(
        character in _MOJIBAKE_MARKERS or character in _C1_CONTROLS
        for character in text
    )


def _reverse_cp1252_utf8(text: str) -> Optional[str]:
    """Reverse a complete CP1252-decoded UTF-8 string, or reject it safely."""
    original_bytes = bytearray()

    for character in text:
        byte_value = _CP1252_REVERSE.get(character)
        if byte_value is None:
            return None
        original_bytes.append(byte_value)

    try:
        return original_bytes.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        return None


def _repair_plain_text(text: str) -> str:
    repaired = text

    for _ in range(3):
        next_repaired = _repair_plain_text_once(repaired)
        if next_repaired == repaired:
            return repaired
        repaired = next_repaired

    return repaired


def _repair_plain_text_once(text: str) -> str:
    original_score = _mojibake_score(text)
    if original_score == 0:
        return text

    repaired = _reverse_cp1252_utf8(text)
    if (
        repaired is not None
        and repaired != text
        and _mojibake_score(repaired) < original_score
    ):
        return repaired

    repaired = _SUSPICIOUS_RUN_PATTERN.sub(_repair_suspicious_run, text)
    if repaired != text:
        return repaired

    # Handle a common mixed-content artifact where otherwise-valid Unicode
    # contains a double-decoded non-breaking space.
    return text.replace("\u00c2\u00a0", "\u00a0")


def _repair_suspicious_run(match: re.Match[str]) -> str:
    text = match.group(0)
    repaired = _repair_candidate(text)
    if repaired is not None:
        return repaired

    for index in range(len(text) - 1, 0, -1):
        repaired_prefix = _repair_candidate(text[:index])
        if repaired_prefix is not None:
            return repaired_prefix + text[index:]

    return text


def _repair_candidate(text: str) -> Optional[str]:
    original_score = _mojibake_score(text)
    repaired = _reverse_cp1252_utf8(text)

    if (
        repaired is not None
        and repaired != text
        and _mojibake_score(repaired) < original_score
    ):
        return repaired

    return None


def repair_mojibake_text(text: str) -> str:
    """Repair text while preserving every ``<img ...>`` tag exactly."""
    if not isinstance(text, str) or not text:
        return text

    if "<img" not in text.lower():
        return _repair_plain_text(text)

    parts = _IMG_TAG_PATTERN.split(text)
    return "".join(
        part if _IMG_TAG_PATTERN.fullmatch(part) else _repair_plain_text(part)
        for part in parts
    )


def _repair_value(value: Any) -> Any:
    if isinstance(value, str):
        return repair_mojibake_text(value)
    if isinstance(value, dict):
        return {key: _repair_value(child) for key, child in value.items()}
    if isinstance(value, list):
        return [_repair_value(child) for child in value]
    return value


def repair_question_mojibake(question: Any) -> Any:
    """Repair every string field in a question payload."""
    if not isinstance(question, dict):
        return question

    return _repair_value(question)
