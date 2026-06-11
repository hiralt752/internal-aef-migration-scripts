from bs4 import BeautifulSoup
import re

# Pre-compiled patterns for faster matching
PASSAGE_KEYS = frozenset(("passage",))
HINT_KEYS = frozenset(("hint", "hints"))
TABLE_PATTERN = re.compile(r'<table\b', re.IGNORECASE)


def _walk(obj):
    """Stack-based walk - optimized."""
    stack = [obj]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            for k, v in node.items():
                yield k, v
                stack.append(v)
        elif isinstance(node, list):
            for item in node:
                stack.append(item)


def has_passage(data) -> bool:
    """Check for passage key with non-empty value."""
    for key, value in _walk(data):
        if isinstance(key, str) and key.lower() in PASSAGE_KEYS:
            if value not in (None, "", [], {}):
                return True
    return False


def has_multiple_hints(data) -> bool:
    """Count hint keys - exit early if > 1."""
    count = 0
    for key, _ in _walk(data):
        if isinstance(key, str) and key.lower() in HINT_KEYS:
            count += 1
            if count > 1:  # Early exit
                return True
    return False


def contains_table_tag(data) -> bool:
    """Check for <table> tag using pre-compiled regex."""
    for _, value in _walk(data):
        if isinstance(value, str):
            # Regex check before BeautifulSoup (faster)
            if TABLE_PATTERN.search(value):
                if BeautifulSoup(value, "html.parser").find("table"):
                    return True
    return False


def should_skip_question(data) -> bool:
    """Short-circuit evaluation - return True as soon as any condition matches."""
    return has_passage(data) or has_multiple_hints(data) or contains_table_tag(data)