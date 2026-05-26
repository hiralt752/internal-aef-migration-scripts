from parsers.content_parser import parse_html_content
from parsers.media_parser import (
    extract_audio,
    extract_video,
    extract_image
)


def build_item_body(raw):

    body = raw.get("body", {})

    choices = body.get("choices", {})

    prompt = body.get("prompt", "")

    parsed_prompt = parse_html_content(
        prompt
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
                )
            )
    }


def build_options(choice_items):

    options = []

    for choice in choice_items:

        parsed_content = parse_html_content(
            choice.get(
                "answer",
                ""
            )
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
                        )
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