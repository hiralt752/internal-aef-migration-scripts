import os
import re
import json
from bs4 import BeautifulSoup
from helpers.debug_logger import DebugLogger

FILTER_JSON_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "filter",
    "dummy_span_texts.json" #add filter file here
)

def clean_text(text: str) -> str:
    """Normalize whitespace and decode common HTML/unicode space characters."""
    if not text:
        return ""
    text = text.replace("&nbsp;", " ").replace("\xa0", " ")
    return re.sub(r'\s+', ' ', text).strip()

FILTER_TEXTS_SET = set()
if os.path.exists(FILTER_JSON_PATH):
    try:
        with open(FILTER_JSON_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                FILTER_TEXTS_SET = {clean_text(t) for t in data if t}
    except Exception as e:
        print(f"Error loading dummy span texts in span_remover.py: {e}")

logger = DebugLogger()

def remove_matching_spans(html_content: str, filter_texts_set: set, question_id=None, lesson=None, file_path=None) -> str:
    """
    Parses html_content, finds span tags, and decomposes them if their text
    content (normalized) exists in filter_texts_set.
    Cleans up any resulting empty parent elements.
    """
    if not html_content or not isinstance(html_content, str):
        return html_content

    soup = BeautifulSoup(html_content, "html.parser")
    
    protected_tags = {"img", "audio", "video", "blank-field", "iframe", "source", "br", "hr", "input", "link", "meta"}

    for span in soup.find_all("span"):
        text = span.get_text()
        normalized = clean_text(text)
        if normalized in filter_texts_set:
            nested_protected = [t for t in span.find_all() if t.name in protected_tags]
            for pt in nested_protected:
                span.insert_before(pt)
            span.decompose()
            
            logger.log(
                question_id=question_id,
                lesson=lesson,
                question_type="SPAN_REMOVER",
                reason=f"Removed span text: '{normalized}'",
                file_path=file_path
            )

    return str(soup)

def remove_span_texts_from_html(html_content: str, question_id=None, lesson=None, file_path=None) -> str:
    """
    Main helper function to remove matching span texts from HTML content
    based on the globally loaded filter set.
    """
    return remove_matching_spans(html_content, FILTER_TEXTS_SET, question_id, lesson, file_path)
