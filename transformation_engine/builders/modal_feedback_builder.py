from parsers.content_parser import parse_html_content
from parsers.media_parser import extract_audio


def build_passage(passage):
    if not isinstance(passage, dict):
        return None

    content_html = passage.get("content") or ""
    parsed_content = parse_html_content(content_html, None, None)

    content_items = [
        item for item in parsed_content
        if item.get("type") in {"text", "image"}
    ]

    if not content_items:
        return None

    return {
        "content": {
            "layout": "text",
            "content": content_items
        },
        "contentTitle": passage.get("title"),
        "contentAudio": extract_audio(content_html)
    }


def build_modal_feedback(
    raw,
    feedback_mapping
):

    source = raw.get("response", raw)
    body = source.get("body", {}) if isinstance(source, dict) else {}

    modal = {}

    need_help = (
        feedback_mapping.get(
            "needHelp",
            []
        )
    )

    if need_help:

        modal["needHelp"] = {

            "content": {

                "layout": "TEXT",

                "content":
                    need_help
            }
        }

    passage = build_passage(body.get("passage"))
    if need_help:
        modal["needHelpStrategy"] ="SCAFFOLDED"   
    if passage:
        modal["passage"] = passage

    return modal if modal else None
