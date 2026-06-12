from bs4 import BeautifulSoup
from parsers.content_parser import parse_html_content


def replace_blank_fields(html):
    """Replace <blank-field> tags with @_@ placeholder."""

    if not html:
        return ""

    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    # Clean up disallowed tags in a single pass
    for tag in soup.find_all(["div", "colgroup", "col", "audio", "video", "a", "pre"]):
        if not tag.parent:
            continue
        if tag.name in ["colgroup", "col", "audio", "video"]:
            tag.decompose()
        elif tag.get("id") == "gtx-trans" or "gtx-trans-icon" in tag.get("class", []):
            tag.decompose()
        else:
            tag.unwrap()

    for tag in soup.find_all(["sup", "sub"]):
        tag.unwrap()

    for blank in soup.find_all(
        "blank-field"
    ):
        blank.replace_with("@_@")

    return str(soup)


def html_to_text(html):
    """Strip HTML to plain text."""

    if not html:
        return ""

    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    return soup.get_text(
        " ",
        strip=True
    )


def normalize_weight(weight):

    return round(
        weight / 100,
        4
    )


def build_fib_dnd_item_body(raw, question_id, lesson):

    body = raw.get("body", {})

    choices = body.get("choices", {})

    return {

        "version": "1.0",

        "title": None,

        "subTitle": None,

        "instruction": None,

        "audio": None,

        "video": None,

        "image": None,

        "backgroundLayout": None,

        "timeSpentConfig": None,

        "splitContent": None,

        "sideImage": None,

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

        "statement": None,

        "sentence": {
            "text":
                replace_blank_fields(
                    body.get("prompt")
                )
        },

        "targets":
            build_fib_targets(
                body.get("blanks", [])
            ),

        "options":
            build_fib_options(
                choices.get(
                    "choiceItems",
                    []
                ), question_id, lesson
            )
    }


def build_fib_targets(blanks):

    targets = []

    for index, blank in enumerate(
        blanks,
        start=1
    ):

        targets.append({

            "id": index,

            "weight":
                normalize_weight(
                    blank.get(
                        "weight",
                        100
                    )
                ),

            "swappable": False,

            "swapGroupId": 0,

            "position": None
        })

    if targets:
        total_weight = sum(t["weight"] for t in targets)
        if total_weight > 0 and round(total_weight, 4) != 1.0:
            diff = 1.0 - total_weight
            targets[0]["weight"] = round(targets[0]["weight"] + diff, 4)

    return targets


def build_fib_options(choice_items, question_id, lesson):

    options = []

    for index, choice in enumerate(
        choice_items,
        start=1
    ):

        options.append({

            "id": index,
            "content": {
                
                "type": "text",
                "text":
                    html_to_text(
                        choice.get(
                            "value",
                            ""
                        )
                    )
            }
        })

    return options
 