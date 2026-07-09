from image_resolution_engine.helpers.image_scanner import scan_json
from image_resolution_engine.helpers.generic import get_see_why_widget_type
from image_resolution_engine.WIDGET_LAYOUT_MAP import get_widget_resolution
import re


# --------------------------------------------------
# Image detection
# --------------------------------------------------

IMG_PATTERNS = (
    re.compile(r"<img", re.IGNORECASE),
    re.compile(r"wiris", re.IGNORECASE),
    re.compile(r"data:image", re.IGNORECASE),
)


def _has_image(value: str):
    if not value or not isinstance(value, str):
        return False
    value = value.lower()
    return any(p.search(value) for p in IMG_PATTERNS)


# --------------------------------------------------
# Audit helper
# --------------------------------------------------

def _build_audit_entries(images, image_role, widget_type, resolution, section=None, content_index=None):

    if not images:
        return []

    return [
        {
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
        for img in images
    ]


def _get_html_audit_entries(html_content, image_role, section=None, content_index=None):

    if not html_content:
        return []

    images = scan_json({image_role: html_content})
    if not images:
        return []

    widget_type = get_see_why_widget_type(html_content) or "See Why/Need Help (mainimage)"
    resolution = get_widget_resolution(widget_type)

    return _build_audit_entries(
        images=images,
        image_role=image_role,
        widget_type=widget_type,
        resolution=resolution,
        section=section,
        content_index=content_index
    )


# --------------------------------------------------
# MAIN ANALYZER (FIXED)
# --------------------------------------------------

def analyze_dropdown(data, q_type, category):

    question_id = data.get("question_id") or data.get("id")
    response = data.get("response", {})
    body = response.get("body", {})

    blanks = body.get("blanks", {}).get("blankItems", [])
    if not blanks:
        return None

    option_count = len(blanks)

    # --------------------------------------------------
    # Widget classification
    # --------------------------------------------------

    has_image_in_option = any(
        _has_image(choice.get("value", ""))
        for b in blanks
        for choice in b.get("choices", [])
    )

    widget_type = (
        "Dropdown (halfimage)"
        if has_image_in_option
        else f"Dropdown ({option_count}cards)"
    )

    resolution = get_widget_resolution(widget_type)

    # --------------------------------------------------
    # QUESTION IMAGES (STRICT SOURCE ONLY)
    # --------------------------------------------------

    question_images = scan_json({
        "prompt": body.get("prompt", "")
    })

    # --------------------------------------------------
    # OPTION IMAGES (STRICT FROM BLANK STRUCTURE ONLY)
    # --------------------------------------------------

    option_images = []

    for b in blanks:
        option_images.extend(scan_json(b))

    # --------------------------------------------------
    # IMAGE AUDIT
    # --------------------------------------------------

    image_audit = []

    image_audit.extend(
        _build_audit_entries(
            question_images,
            "question",
            widget_type,
            resolution,
            section="question"
        )
    )

    image_audit.extend(
        _build_audit_entries(
            option_images,
            "option",
            widget_type,
            resolution,
            section="options"
        )
    )

    # --------------------------------------------------
    # FEEDBACK (ONLY BODY FIELDS)
    # --------------------------------------------------

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

    # --------------------------------------------------
    # HINTS
    # --------------------------------------------------

    for idx, hint in enumerate(body.get("hints", [])):
        image_audit.extend(
            _get_html_audit_entries(
                hint,
                image_role="hint",
                section="hints",
                content_index=idx
            )
        )

    # passage audit
    passage = body.get("passage")
    if isinstance(passage, dict):
        passage_content = passage.get("content", "")
        image_audit.extend(
            _get_html_audit_entries(
                passage_content,
                image_role="passage",
                section="passage"
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
        "option_count": option_count,
        "resolution": resolution,
        "question_images": question_images,
        "option_images": option_images,
        "image_audit": image_audit
    }