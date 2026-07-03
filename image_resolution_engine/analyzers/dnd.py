from image_resolution_engine.helpers.image_scanner import scan_json
from image_resolution_engine.helpers.generic import get_see_why_widget_type
from image_resolution_engine.WIDGET_LAYOUT_MAP import get_widget_resolution
import re


# --------------------------------------------------
# Blank Detection
# --------------------------------------------------

BLANK_PATTERNS = (
    re.compile(r'\{\{blank\}\}', re.IGNORECASE),
    re.compile(r'<\s*blank\s*>', re.IGNORECASE),
    re.compile(r'blank[-_\s]?field', re.IGNORECASE),
    re.compile(r'fill\s*in\s*the\s*blank', re.IGNORECASE),
    re.compile(r'_{2,}', re.IGNORECASE),
)


def _has_blanks(data: dict) -> bool:
    text = str(data)
    return any(p.search(text) for p in BLANK_PATTERNS)


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
        _build_audit_entry(
            img,
            image_role,
            widget_type,
            resolution,
            section,
            content_index
        )
        for img in images
    ]


# --------------------------------------------------
# Main Analyzer
# --------------------------------------------------

def analyze_dnd(data, q_type, category):

    question_id = data.get("question_id") or data.get("id")
    body = data.get("response", {}).get("body", {})
    back_ground_image  = body.get("backgroundImage")
    images = scan_json(data)
    if not images:
        return None

    # --------------------------------------------------
    # CLASSIFICATION (FIXED)
    # --------------------------------------------------

    question_images = []
    option_images = []
    feedback_images = []

    for img in images:
        key = img.get("key", "")

        # -----------------------------
        # FEEDBACK → ONLY AUDIT
        # -----------------------------
        if "generalFeedback" in key:
            feedback_images.append(img)
            continue

        if "correctAnswerFeedback" in key:
            feedback_images.append(img)
            continue

        if "wrongAnswerFeedback" in key:
            feedback_images.append(img)
            continue

        if "partialAnswerFeedback" in key:
            feedback_images.append(img)
            continue

        # -----------------------------
        # OPTION IMAGES
        # -----------------------------
        if "choiceItems" in key:
            option_images.append(img)
        else:
            question_images.append(img)

    # --------------------------------------------------
    # BACKGROUND IMAGE
    # --------------------------------------------------

    if isinstance(back_ground_image, dict) and back_ground_image.get("src"):
        question_images.append({
            "key": "backgroundImage",
            "src": back_ground_image.get("src")
        })

    # --------------------------------------------------
    # WIDGET TYPE
    # --------------------------------------------------

    option_count = len(option_images)
    blank_present = _has_blanks(data)

    if question_images and not option_images:
        widget_type = "Drag and Drop (mainimage)"
    elif question_images and option_count == 4:
        widget_type = "Drag and Drop (4imageoptions)"
    elif question_images and option_count <= 2:
        widget_type = "Drag and Drop (SplitScreenImage)"
    else:
        widget_type = f"Drag and Drop (custom-{option_count}options)"

    if blank_present:
        widget_type = "Drag and Drop (FIB_DRAG)"

    resolution = get_widget_resolution(widget_type)

    # --------------------------------------------------
    # IMAGE AUDIT (ONLY GENERAL FEEDBACK)
    # --------------------------------------------------

    image_audit = []

    
    general_feedback = body.get("generalFeedback", "")

    image_audit.extend(
        _get_html_audit_entries(
            general_feedback,
            image_role="generalFeedback",
            section="generalFeedback"
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