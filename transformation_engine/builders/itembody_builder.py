from parsers.content_parser import parse_html_content
from parsers.media_parser import (
    extract_audio,
    extract_video,
    extract_image
)
from bs4 import BeautifulSoup
def _extract_side_image_from_sentence(sentence_html):
    soup = BeautifulSoup(sentence_html or "", "html.parser")
    img = soup.find("img")
    if not img:
        return sentence_html, None

    url = img.get("src")
    img.decompose()
    cleaned = str(soup).strip()
    return cleaned, {"url": url} if url else None


def build_item_body(raw, question_type=None, fib_data=None,question_id=None,lesson=None):
    if question_type == "FIB":
        return build_fib_item_body(raw, fib_data)

    return build_item_body_mcq(raw,question_id,lesson)

def build_item_body_mcq(raw,question_id,lesson):

    body = raw.get("body", {})

    choices = body.get("choices", {})

    prompt = body.get("prompt", "")

    parsed_prompt = parse_html_content(
        prompt,question_id,lesson
    )

    audio = extract_audio(prompt)

    video = extract_video(prompt)

    image = extract_image(prompt)

    return {

        "version": "1.0",

        "statement": {
            "content": parsed_prompt
        } if parsed_prompt else None,

        "instruction": None,

        "audio": audio,

        "stemVideo": video,

        "stemImage": None,

        "shuffled":
            choices.get(
                "shuffle",
                True
            ),

        "columns":
            choices.get(
                "layoutColumns",
                2
            ),

        "listType":
            choices.get(
                "listType",
                "NONE"
            ),

        "allowTryAgain": False,

        "hasActiveVideoBreakpoint": False,

        "title": None,

        "subTitle": None,

        "video": None,

        "backgroundLayout": None,

        "splitContent": None,

        "timeSpentConfig": None,

        "options":
            build_options(
                choices.get(
                    "choiceItems",
                    []
                ),question_id,lesson
            )
    }


def build_options(choice_items,question_id,lesson):

    options = []

    for choice in choice_items:

        parsed_content = parse_html_content(
            choice.get(
                "answer",
                ""
            ),question_id,lesson
        )

        option_feedback = choice.get(
            "feedback",
            ""
        )

        option = {

            "optionId":
                int(
                    choice.get(
                        "choiceId"
                    )
                ),

            "content":
                _sort_option_content(
                    parsed_content
                )
        }

        if (
            option_feedback
            and option_feedback.strip()
        ):

            option["feedback"] = {

                "general": {

                    "content":
                        parse_html_content(
                            option_feedback
                        ,question_id,lesson)
                }
            }

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

def build_fib_item_body(raw,fib_data):
    body = raw.get("body", {})
    prompt = body.get("prompt", "")
    sentence_text, side_image = _extract_side_image_from_sentence(fib_data.get("sentence_text", ""))

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
        "sideImage": side_image,
        "fibImage": extract_image(prompt),
        "optionsStyle": "option-style-1",
        "wordBankLayout": "none",
        "wordBankDistractor": [],
        "columns": 1,
        "numberedSentence": False,
        "centered": False,
        "statement": {
            "content": {
                "type": "text",
                "text": ""
            }
        },
        "sentence": {
            "text": sentence_text
        },
        "items": fib_data["items"],
        "variables": []
    }
