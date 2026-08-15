from parsers.content_parser import (
    parse_html_content,
    strip_disallowed_tags,
    split_html_only_feedback_content
)
from parsers.media_parser import (
    extract_audio,
    extract_video
)
from bs4 import BeautifulSoup
from helpers.span_remover import remove_span_texts_from_html
from urllib.parse import unquote


def _extract_side_image_from_sentence(sentence_html):
    soup = BeautifulSoup(sentence_html or "", "html.parser")
    img = soup.find("img")

    if not img:
        return sentence_html, None

    url = img.get("src") or ""
    classes = img.get("class") or []

    # Ignore WIRIS MathML SVG images (do NOT decompose math images!)
    if url.startswith("data:image/svg+xml"):
        decoded_svg = unquote(url)

        if "MathML:" in decoded_svg or (
            "<math" in decoded_svg and "MathML" in decoded_svg
        ):
            return sentence_html, None

    if img.get("data-mathml") or "Wirisformula" in classes:
        return sentence_html, None

    img.decompose()
    cleaned = str(soup).strip()
    return strip_disallowed_tags(cleaned), {"url": url} if url else None


def build_item_body(raw, question_type=None, fib_data=None, question_id=None, lesson=None, file_path=None):
    if question_type == "FIB":
        return build_fib_item_body(raw, fib_data, question_id, lesson)

    return build_item_body_mcq(raw, question_id, lesson, file_path)


def build_item_body_mcq(raw, question_id, lesson, file_path=None):
    body = raw.get("body", {})
    choices = body.get("choices", {})
    prompt = body.get("prompt", "")

    prompt = remove_span_texts_from_html(prompt, question_id, lesson, file_path)

    audio = extract_audio(prompt)
    video = extract_video(prompt)

    parsed_prompt = parse_html_content(
        prompt, question_id, lesson
    )

    if not parsed_prompt :
        parsed_prompt = [{ 
            'type':'text',
            'text':'<p></p>'
        }]

    return {
        "version": "1.0",
        "statement": {
            "content": parsed_prompt
        } if parsed_prompt else None,
        "instruction": None,
        "audio": audio,
        "stemVideo": video,
        "stemImage": None,
        "shuffled": choices.get("shuffle", True),
        "columns": choices.get("layoutColumns", 2),
        "listType": choices.get("listType", "NONE"),
        "allowTryAgain": False,
        "hasActiveVideoBreakpoint": False,
        "title": None,
        "subTitle": None,
        "video": None,
        "backgroundLayout": None,
        "splitContent": None,
        "timeSpentConfig": None,
        "options": build_options(choices.get("choiceItems", []), question_id, lesson)
    }


def build_options(choice_items, question_id, lesson):
    options = []

    for choice in choice_items:
        parsed_content = parse_html_content(
            choice.get("answer", ""),
            question_id,
            lesson
        )

        option_feedback = choice.get("feedback", "")

        option = {
            "optionId": int(choice.get("choiceId")),
            "content": _sort_option_content(parsed_content)
        }

        if option_feedback and option_feedback.strip():
            # itemBody.options[].feedback.general.content is Html[] (text-only,
            # no "table"/"video" field, single sibling "audio" field) - keep
            # any table inline and route audio/drop video accordingly.
            feedback_items = parse_html_content(
                option_feedback, question_id, lesson, extract_table=False
            )
            feedback_content, feedback_audio = split_html_only_feedback_content(
                feedback_items, question_id, lesson
            )
            option["feedback"] = {
                "general": {"content": feedback_content}
            }
            if feedback_audio:
                option["feedback"]["general"]["audio"] = feedback_audio
        else:
            option["feedback"] = None

        options.append(option)

    return options


def _sort_option_content(contents):
    image_items = []
    other_items = []

    for item in contents:
        if item.get("type") == "image":
            image_items.append(item)
        else:
            other_items.append(item)

    return image_items + other_items


def build_fib_item_body(raw, fib_data, question_id, lesson):
    body = raw.get("body", {})
    prompt = body.get("prompt", "")
    transformed_prompt = (
        fib_data.get("sentence_text")
        if fib_data and fib_data.get("sentence_text") is not None
        else prompt
    )

    # sentence is FIBHtml (schema: {"text": string}) - a plain string field,
    # not a ContentItem[], so a <table> can never become a structured "table"
    # object here. extract_table=False keeps it as raw inline HTML inside the
    # text instead of being pulled into a separate tableless first item.
    sentence_text = parse_html_content(
        transformed_prompt, question_id, lesson, extract_table=False
    )
    _, image = _extract_side_image_from_sentence(transformed_prompt)

    sideImage = {
        "url": image["url"] if image else ""
    }

    return {
        "version": "1.0",
        "title": None,
        "subTitle": None,
        "instruction": None,
        "audio": extract_audio(prompt),
        "video": extract_video(prompt),
        "backgroundLayout": None,
        "timeSpentConfig": None,
        "splitContent": None,
        "sideImage": sideImage if sideImage["url"] != "" else None,
        "fibImage": sideImage if sideImage["url"] != "" else None,
        "optionsStyle": "option-style-1",
        "wordBankLayout": "none",
        "wordBankDistractor": [],
        "columns": 1,
        "numberedSentence": False,
        "centered": False,
        "statement": {
            "content": {
                "type": "text",
                "text": "<p></p>"
            }
        },
        "sentence": {
            "type": sentence_text[0]["type"] if sentence_text else "text",
            # Not every parsed content type carries "text" (image/audio/
            # video don't) - fall back to "" instead of KeyError.
            "text": sentence_text[0].get("text", "") if sentence_text else ""
        },
        "items": fib_data["items"],
        "variables": []
    }
