from parsers.content_parser import parse_html_content


def build_image_labelling_dnd_item_body(raw,question_id,lesson):

    body = raw.get("body", {})

    choices = body.get("choices", {})
    
    return {

        "version": "1.0",

        "title": None,

        "subTitle": None,

        "instruction": None,

        "audio": None,

        "video": None,

        "statement": None,

        "sentence": None,

        "image":
            body.get(
                "backgroundImage"
            ),

        "showDragHandle":
            choices.get(
                "showDragHandle",
                True
            ),

        "shuffled":
            choices.get(
                "shuffle",
                True
            ),

        "optionsStyle": "option-style-1",

        "dropLimit": 1,

        "optionsPosition": "bottom",

        "sideImage": None,

        "backgroundLayout": None,

        "splitContent": None,

        "timeSpentConfig": None,

        "targets":
            build_targets(
                body.get(
                    "blanks",
                    []
                )
            ),

        "options":
            build_image_labelling_options(
                choices.get(
                    "choiceItems",
                    []
                ),question_id,lesson
            )
    }


def build_targets(blanks):

    targets = []

    for index, blank in enumerate(blanks, start=1):
        position = blank.get("position", {})
        targets.append({

            "id": index,

            "weight": round(
                (
                    blank.get(
                        "weight",
                        0
                    ) / 100
                ),
                4
            ),

            "position": {
                "left": int(round(position.get("x", 0) * 100)),
                "top": int(round(position.get("y", 0) * 100)),
                "width": 100
            },
            "swappable":False,
            "swapGroupId":0
        })

    return targets


def build_image_labelling_options(choice_items,question_id,lesson):

    options = []

    for index, choice in enumerate(choice_items, start=1):

        parsed_content = parse_html_content(
            choice.get(
                "value",
                ""
            ),question_id,lesson
        )

        option_feedback = choice.get(
            "feedback",
            ""
        )

        option = {

            "id": index,

            "content":
                _sort_option_content(
                    parsed_content
                )
        }

        options.append(option)

    return options


def _sort_option_content(contents):

    return (
        next((item for item in contents if item.get("type") == "image"), None)
        or next((item for item in contents if item), None)
    )