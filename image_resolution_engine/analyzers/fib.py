from bs4 import BeautifulSoup
from image_resolution_engine.helpers.image_scanner import scan_json
from image_resolution_engine.helpers.generic import get_see_why_widget_type
from image_resolution_engine.WIDGET_LAYOUT_MAP import get_widget_resolution
import re


# --------------------------------------------------
# Blank Detection
# --------------------------------------------------

BLANK_PATTERNS = (
    re.compile(r"\{\{blank\}\}", re.IGNORECASE),
    re.compile(r"<blank>", re.IGNORECASE),
    re.compile(r"blank-field", re.IGNORECASE),
    re.compile(r"fill in the blank", re.IGNORECASE),
)


def _safe_int(value):
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None


def _has_blanks(text: str):
    text_lower = text.lower() if isinstance(text, str) else ""
    return any(p.search(text_lower) for p in BLANK_PATTERNS)


# --------------------------------------------------
# Audit Helpers
# --------------------------------------------------

def _build_audit_entry(img, image_role, widget_type, resolution, section=None, content_index=None):
    if not img:
        return None

    return {
        "image_role": image_role,
        "section": section,
        "content_index": content_index,
        "src": img.get("src"),
        "content_type": img.get("content_type", "IMAGE"),
        "width": img.get("width"),
        "height": img.get("height"),
        "key": img.get("key"),
        "widget_type": widget_type,
        "max_width": resolution.get("max_width"),
        "max_height": resolution.get("max_height"),
        "ratio": resolution.get("ratio")
    }


def _get_html_audit_entries(html_content, image_role, section=None, content_index=None):

    if not html_content:
        return []

    images = scan_json({image_role: html_content})
    if not images:
        return []

    widget_type = get_see_why_widget_type(html_content)
    if not widget_type:
        return []

    resolution = get_widget_resolution(widget_type)

    return [
        _build_audit_entry(img, image_role, widget_type, resolution, section, content_index)
        for img in images
    ]


# --------------------------------------------------
# MAIN ANALYZER
# --------------------------------------------------

def analyze_fib(data, q_type, category):

    question_id = data.get("question_id") or data.get("id")
    response = data.get("response", {})
    body = response.get("body", {})

    # --------------------------------------------------
    # RAW IMAGE EXTRACTION
    # --------------------------------------------------

    all_images = scan_json(data)
    if not all_images:
        return None

    question_images = []
    feedback_images = []
    hint_images = []

    # --------------------------------------------------
    # STRICT CLASSIFICATION (NO FALLBACK BUG)
    # --------------------------------------------------

    for img in all_images:
        key = img.get("key", "")

        # -------------------------
        # HINT IMAGES (STRICT)
        # -------------------------
        if "hints" in key:
            hint_images.append(img)
            continue

        # -------------------------
        # FEEDBACK IMAGES (AUDIT ONLY)
        # -------------------------
        if any(x in key for x in [
            "generalFeedback",
            "correctAnswerFeedback",
            "wrongAnswerFeedback",
            "partialAnswerFeedback"
        ]):
            feedback_images.append(img)
            continue

        # -------------------------
        # QUESTION IMAGES ONLY
        # -------------------------
        question_images.append(img)

    # --------------------------------------------------
    # IMAGE ORIENTATION LOGIC
    # --------------------------------------------------

    portrait_count = 0
    landscape_count = 0

    for img in question_images:
        width = _safe_int(img.get("width"))
        height = _safe_int(img.get("height"))

        if width and height:
            if height > width:
                portrait_count += 1
            else:
                landscape_count += 1

    prompt = body.get("prompt", "")
    text = BeautifulSoup(prompt, "html.parser").get_text(" ").lower() if prompt else ""

    has_blanks = _has_blanks(text)

    if has_blanks:
        widget_type = "FIB Blanks"
    elif portrait_count > landscape_count:
        widget_type = "FIB (fullimage)"
    else:
        widget_type = "FIB (halfimage)"

    resolution = get_widget_resolution(widget_type)

    # --------------------------------------------------
    # IMAGE AUDIT (ONLY FEEDBACK + HINTS)
    # --------------------------------------------------

    image_audit = []

    # feedback audit
    for field in [
        "generalFeedback",
        "correctAnswerFeedback",
        "wrongAnswerFeedback",
        "partialAnswerFeedback"
    ]:
        image_audit.extend(
            _get_html_audit_entries(
                body.get(field, ""),
                image_role=field,
                section=field
            )
        )

    # hints audit
    hints = body.get("hints", [])

    for idx, hint in enumerate(hints):
        image_audit.extend(
            _get_html_audit_entries(
                hint,
                image_role="hint",
                section="hints",
                content_index=idx
            )
        )

    # --------------------------------------------------
    # RETURN
    # --------------------------------------------------

    return {
        "question_id": question_id,
        "widget_type": widget_type,
        "category": category,
        "source_type": q_type,
        "option_count": 0,
        "resolution": resolution,
        "question_images": question_images,
        "option_images": [],
        "image_audit": image_audit
    }