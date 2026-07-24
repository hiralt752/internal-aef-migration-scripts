import os
import re
import json
from html import unescape
from bs4 import BeautifulSoup
from helpers.debug_logger import DebugLogger

FILTER_JSON_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "filter",
    "instructions.json" #add filter file here
)

def clean_text(text: str) -> str:
    """Normalize whitespace and decode common HTML/unicode space characters."""
    if not text:
        return ""
    text = unescape(text)
    text = (
        text.replace("&nbsp;", " ")
        .replace("\xa0", " ")
        .replace("\ufeff", "")
        .replace("\u200b", "")
    )
    return re.sub(r'\s+', ' ', text).strip()

FILTER_TEXTS_SET = set()
FILTER_CANONICAL_TEXTS_SET = set()
ARABIC_CHAR_NORMALIZATION = str.maketrans({
    "\u0623": "\u0627",  # أ -> ا
    "\u0625": "\u0627",  # إ -> ا
    "\u0622": "\u0627",  # آ -> ا
    "\u0671": "\u0627",  # ٱ -> ا
    "\u0649": "\u064a",  # ى -> ي
})


def canonical_instruction_text(text: str) -> str:
    """Normalize text for instruction matching without changing emitted content."""
    text = clean_text(text).casefold()
    text = re.sub(r"[\u064b-\u065f\u0670\u0640]", "", text)
    text = text.translate(ARABIC_CHAR_NORMALIZATION)
    text = re.sub(r"[^\w\u0600-\u06ff]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


if os.path.exists(FILTER_JSON_PATH):
    try:
        with open(FILTER_JSON_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                FILTER_TEXTS_SET = {clean_text(t) for t in data if t}
                FILTER_CANONICAL_TEXTS_SET = {
                    canonical
                    for canonical in (canonical_instruction_text(t) for t in data if t)
                    if canonical
                }
    except Exception as e:
        print(f"Error loading dummy span texts in span_remover.py: {e}")

logger = DebugLogger()

PROTECTED_TAGS = {"img", "audio", "video", "blank-field", "iframe", "source", "br", "hr", "input", "link", "meta"}
REMOVABLE_TAGS = {"span", "strong", "b", "em", "i", "p"}
EMPTY_CONTAINER_TAGS = {"span", "strong", "b", "em", "i", "p", "div"}


def _has_protected_descendant(tag) -> bool:
    return bool(tag.find(list(PROTECTED_TAGS)))


def _preserve_protected_descendants(tag) -> None:
    for protected in list(tag.find_all(list(PROTECTED_TAGS))):
        tag.insert_before(protected.extract())


def _remove_empty_containers(soup: BeautifulSoup) -> bool:
    removed_any = False
    changed = True
    while changed:
        changed = False
        for tag in list(soup.find_all(list(EMPTY_CONTAINER_TAGS))):
            if _has_protected_descendant(tag):
                continue
            if clean_text(tag.get_text(" ", strip=True)):
                continue
            tag.decompose()
            changed = True
            removed_any = True
    return removed_any

def _is_filtered_instruction(text: str, filter_texts_set: set) -> bool:
    normalized = clean_text(text)
    if normalized in filter_texts_set:
        return True

    canonical = canonical_instruction_text(normalized)
    return canonical in FILTER_CANONICAL_TEXTS_SET


def remove_matching_spans(html_content: str, filter_texts_set: set, question_id=None, lesson=None, file_path=None) -> str:
    """
    Parses html_content, finds span tags, and decomposes them if their text
    content (normalized) exists in filter_texts_set.
    Cleans up any resulting empty parent elements.
    """
    if not html_content or not isinstance(html_content, str):
        return html_content

    soup = BeautifulSoup(html_content, "html.parser")
    removed_any = False

    for tag in sorted(
        soup.find_all(list(REMOVABLE_TAGS)),
        key=lambda item: len(list(item.parents)),
    ):
        if not tag.parent:
            continue
        text = tag.get_text(" ", strip=True)
        normalized = clean_text(text)
        if _is_filtered_instruction(normalized, filter_texts_set):
            if _has_protected_descendant(tag):
                continue
            tag.decompose()
            removed_any = True
            
            logger.log(
                question_id=question_id,
                lesson=lesson,
                question_type="SPAN_REMOVER",
                reason=f"Removed span text: '{normalized}'",
                file_path=file_path
            )

    if not removed_any:
        return html_content

    _remove_empty_containers(soup)
    return str(soup)

def remove_span_texts_from_html(html_content: str, question_id=None, lesson=None, file_path=None) -> str:
    """
    Main helper function to remove matching span texts from HTML content
    based on the globally loaded filter set.
    """
    return remove_matching_spans(html_content, FILTER_TEXTS_SET, question_id, lesson, file_path)
