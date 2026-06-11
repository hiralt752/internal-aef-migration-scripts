from helpers.image_scanner import scan_json
from constants.qtype_map import normalize_qtype
from WIDGET_LAYOUT_MAP import get_widget_resolution


# --------------------------------------------------
# Widget Type Builder
# --------------------------------------------------

def _get_widget_type(has_q_img, has_o_img, qtype, count):

    if has_q_img and not has_o_img:
        return f"{qtype} (image+{count}options)"

    if not has_q_img and has_o_img:
        return f"{qtype} ({count}imageoptions)"

    if has_q_img and has_o_img:
        return f"{qtype} (text/image+{count}imageoptions)"

    return f"{qtype} (text+{count}options)"


# --------------------------------------------------
# SAFE SCANNER (DEDUP INSIDE)
# --------------------------------------------------

def _safe_scan(source, seen):
    images = scan_json(source) or []

    unique = []
    for img in images:
        src = img.get("src")
        if not src or src in seen:
            continue

        seen.add(src)

        unique.append({
            "src": src,
            "key": img.get("key"),
            "width": img.get("width"),
            "height": img.get("height")
        })

    return unique


# --------------------------------------------------
# AUDIT BUILDER (FIXED - NO DUPLICATE STRUCTURES)
# --------------------------------------------------

def _build_audit_entries(images, image_role, widget_type, resolution,
                         section=None, content_index=None):

    if not images:
        return []

    return [
        {
            "image_role": image_role,
            "section": section,
            "content_index": content_index,
            "src": img["src"],   # ONLY reference
            "widget_type": widget_type,
            "max_width": resolution.get("max_width"),
            "max_height": resolution.get("max_height"),
            "ratio": resolution.get("ratio"),
        }
        for img in images
    ]


# --------------------------------------------------
# MAIN ANALYZER (FIXED)
# --------------------------------------------------

def analyze_mcq(data, q_type, category):

    qtype = normalize_qtype(q_type)

    question_id = data.get("question_id")
    body = data.get("response", {}).get("body", {})

    choices = body.get("choices", {}).get("choiceItems", [])
    option_count = len(choices) if isinstance(choices, list) else 0

    seen = set()  # GLOBAL DEDUP TRACKER

    # --------------------------------------------------
    # QUESTION IMAGES
    # --------------------------------------------------

    question_images = _safe_scan(
        {"prompt": body.get("prompt", "")},
        seen
    )

    # --------------------------------------------------
    # OPTION IMAGES
    # --------------------------------------------------

    option_images = []
    for choice in choices:
        option_images.extend(_safe_scan(choice, seen))

    # --------------------------------------------------
    # WIDGET TYPE
    # --------------------------------------------------

    has_q_img = len(question_images) > 0
    has_o_img = len(option_images) > 0

    widget_type = _get_widget_type(has_q_img, has_o_img, qtype, option_count)

    resolution = get_widget_resolution(widget_type)

    # --------------------------------------------------
    # IMAGE AUDIT (REFERENCE ONLY - NO DUPLICATION)
    # --------------------------------------------------

    image_audit = []

    # --------------------------------------------------
    # FEEDBACK + HINTS (SAFE)
    # --------------------------------------------------

    feedback_fields = [
        "generalFeedback",
        "correctAnswerFeedback",
        "wrongAnswerFeedback",
        "partialAnswerFeedback"
    ]

    for field in feedback_fields:
        image_audit += _build_audit_entries(
            _safe_scan({field: body.get(field, "")}, seen),
            field,
            widget_type,
            resolution,
            section=field
        )

    for idx, hint in enumerate(body.get("hints", [])):
        image_audit += _build_audit_entries(
            _safe_scan({"hint": hint}, seen),
            "hint",
            widget_type,
            resolution,
            section="hints",
            content_index=idx
        )

    # --------------------------------------------------
    # RETURN
    # --------------------------------------------------

    return {
        "question_id": question_id,
        "category": category,
        "source_type": q_type,
        "widget_type": widget_type,
        "resolution": resolution,
        "question_images": question_images,
        "option_images": option_images,
        "option_count": option_count,
        "image_audit": image_audit
    }