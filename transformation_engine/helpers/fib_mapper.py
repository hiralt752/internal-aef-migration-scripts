import re
from parsers.content_parser import parse_html_content
from bs4 import BeautifulSoup
from helpers.span_remover import remove_span_texts_from_html


def get_text_value(value) :
    return value[0].get("text")

def get_list_of_text(value):
    return [v.get("text") for v in value]

def map_fib_structure(raw, qid, lesson, file_path):
    body = raw.get("body", {})
    prompt = body.get("prompt", "")

    prompt = remove_span_texts_from_html(prompt, qid, lesson, file_path)

    soup = BeautifulSoup(
        prompt,
        "html.parser"
    )

    blanks = body.get(
        "blanks",
        []
    )

    blank_lookup = {
        int(x.get("id")): x
        for x in blanks
    }

    validation_lookup = {}
    answer_mapping = (
        raw.get("validation", {})
        .get("validResponse", {})
        .get("answerMapping", [])
    )

    for answer in answer_mapping:
        validation_lookup[
            int(answer.get("blankId"))
        ] = answer

    sequential_id = 1
    items = []
    correct_answers = []

    for blank in soup.find_all("blank-field"):
        old_blank_id = int(
            blank.get("id")
        )

        blank_data = blank_lookup.get(
            old_blank_id,
            {}
        )

        validation_data = validation_lookup.get(
            old_blank_id,
            {}
        )

        correct_answer = (
            validation_data.get(
                "correctAnswer",
                ""
            )
        )

        alternate_answers = (
            validation_data.get(
                "alternateAnswers",
                []
            )
        )

        answer_type = detect_answer_type(
            correct_answer
        )

        item = {
            "id": sequential_id,
            "weight": normalize_weight(
                blank_data.get(
                    "weight",
                    100.0
                )
            ),
            "feedback": blank_data.get(
                "feedback"
            ) or "",
            "rules": blank_data.get(
                "rules",
                []
            ),
            "decimalNotation": blank_data.get(
                "decimalNotation"
            ),
            "periodNotation": blank_data.get(
                "periodNotation"
            ),
            "answerType": answer_type,
            "inputType": blank_data.get(
                "type",
                "TEXT_BLANK"
            ),
            "swappable": False,
            "swapGroupId": 0,
            "withBlankPicker": False,
            "allowEquivalentNumber": False,
            "simplestFormFraction": False,
            "decimals": None,
            "itemId": None,
            "position": None,
            "wirisXml": None,
            "wirisSvg": None
        }

        items.append(item)
        correct_answers.append({
            "blankId": sequential_id,
            "correctAnswer": get_text_value(parse_html_content(correct_answer,None,None)),
            "alternateAnswers": alternate_answers,
            "answerInWidgetFormat": None
        })

        blank.replace_with("@_@")
        sequential_id += 1

    transformed_html = str(soup)

    return {
        "sentence_text": transformed_html,
        "items": items,
        "correct_answers": correct_answers,
        "multiple_answer": False
    }


def normalize_weight(weight):
    try:
        return float(weight) / 100
    except Exception:
        return 1.0


def detect_answer_type(answer):
    if answer is None:
        return "text"

    answer = str(answer).strip()
    if not answer:
        return "text"

    number_pattern = (
        r"^-?\d+(\.\d+)?$"
    )

    if re.fullmatch(
        number_pattern,
        answer
    ):
        return "number"

    formula_indicators = [
        "=",
        "\\frac",
        "\\sqrt",
        "^",
        "+"
    ]

    for token in formula_indicators:
        if token in answer:
            return "calculated"

    return "text"
