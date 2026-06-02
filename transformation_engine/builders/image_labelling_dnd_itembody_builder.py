from parsers.content_parser import parse_html_content


def build_image_labelling_dnd_item_body(raw):

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

        "backgroundImage":
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
                )
            )
    }


def build_targets(blanks):

    targets = []

    for index, blank in enumerate(blanks, start=1):

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

                "x":
                    blank.get(
                        "position",
                        {}
                    ).get("x"),

                "y":
                    blank.get(
                        "position",
                        {}
                    ).get("y")
            }
        })

    return targets


def build_image_labelling_options(choice_items):

    options = []

    for index, choice in enumerate(choice_items, start=1):

        parsed_content = parse_html_content(
            choice.get(
                "value",
                ""
            )
        )

        option_feedback = choice.get(
            "feedback",
            ""
        )

        option = {

            "optionId": index,

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