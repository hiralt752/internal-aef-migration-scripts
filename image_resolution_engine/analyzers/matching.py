from image_resolution_engine.helpers.image_scanner import scan_json
from image_resolution_engine.helpers.generic import get_see_why_widget_type
from image_resolution_engine.WIDGET_LAYOUT_MAP import get_widget_resolution


# --------------------------------------------------
# Audit Helper
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

    widget_type = get_see_why_widget_type(html_content)
    if not widget_type:
        return []

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

def analyze_matching(data, q_type, category):

    question_id = data.get("question_id") or data.get("id")
    response = data.get("response", {})
    body = response.get("body", {})
    matchers = body.get("matchers", {})

    choices = matchers.get("choices", [])
    answers = matchers.get("answers", [])

    if not choices:
        return None

    option_count = len(choices)
    widget_type = f"Matching ({option_count}imageoptions)"
    resolution = get_widget_resolution(widget_type)

    image_audit = []

    # --------------------------------------------------
    # QUESTION IMAGES (ONLY FROM PROMPT / BODY)
    # --------------------------------------------------

    question_images = scan_json({
        "prompt": body.get("prompt", "")
    })

    image_audit.extend(
        _build_audit_entries(
            question_images,
            "question",
            widget_type,
            resolution,
            section="question"
        )
    )

    # --------------------------------------------------
    # OPTION IMAGES (STRICT MATCHERS ONLY)
    # --------------------------------------------------

    option_images = []

    for c in choices:
        option_images.extend(scan_json(c))

    for a in answers:
        option_images.extend(scan_json(a))

    image_audit.extend(
        _build_audit_entries(
            option_images,
            "option",
            widget_type,
            resolution,
            section="matching"
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
    # HINTS (ONLY HINTS ARRAY)
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