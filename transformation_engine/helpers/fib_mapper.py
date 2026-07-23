import re
from urllib.parse import unquote
from parsers.content_parser import parse_html_content
from bs4 import BeautifulSoup
from helpers.span_remover import remove_span_texts_from_html


def get_text_value(value) :
    if not value:
        return ""

    return value[0].get("text")


def extract_correct_answer_text(answer_html, question_id, lesson):
    parsed_answer = parse_html_content(
        answer_html,
        question_id,
        lesson
    )

    text_value = get_text_value(parsed_answer)
    if text_value:
        return text_value

    fallback_text = BeautifulSoup(
        answer_html or "",
        "html.parser"
    ).get_text(" ", strip=True)
    if fallback_text:
        return fallback_text

    return answer_html or ""

def get_list_of_text(value):
    return [v.get("text") for v in value]


def extract_feedback_text(feedback_html, question_id, lesson):
    parsed_feedback = parse_html_content(
        feedback_html or "",
        question_id,
        lesson
    )

    for item in parsed_feedback:
        if item.get("type") == "text" and item.get("text"):
            return item["text"]

    return ""


def build_answer_in_widget_format(
    correct_answer,
    question_id,
    lesson
):
    """Return the primary FIB answer in the API's accepted scalar format."""
    return extract_correct_answer_text(
        correct_answer,
        question_id,
        lesson
    )


def is_legacy_blank_marker(tag):
    """Return True for legacy WIRIS images that represent a FIB blank."""
    if tag.name != "img":
        return False

    marker_data = " ".join([
        tag.get("data-mathml", ""),
        tag.get("alt", ""),
        unquote(tag.get("src", ""))
    ])

    return bool(re.search(r"\bblank(?:\b|_)", marker_data, re.IGNORECASE))

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

    blank_fields = soup.find_all("blank-field")
    if blank_fields:
        blank_sources = [
            (
                blank_lookup.get(int(blank.get("id")), {}),
                int(blank.get("id")),
                blank
            )
            for blank in blank_fields
        ]
    else:

        legacy_markers = [
            image
            for image in soup.find_all("img")
            if is_legacy_blank_marker(image)
        ]
        blank_sources = [
            (
                blank_data,
                int(blank_data.get("id")),
                legacy_markers[index] if index < len(legacy_markers) else None
            )
            for index, blank_data in enumerate(blanks)
        ]

    for blank_data, old_blank_id, blank_marker in blank_sources:

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

        feedback = blank_data.get("feedback") or ""
        parsed_feedback = extract_feedback_text(
            feedback,
            qid,
            lesson
        )

        item = {
            "id": sequential_id,
            "weight": normalize_weight(
                blank_data.get(
                    "weight",
                    100.0
                )
            ),
            "feedback": parsed_feedback,
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
        mapped_correct_answer = extract_correct_answer_text(
            correct_answer,
            qid,
            lesson
        )

        correct_answers.append({
            "blankId": sequential_id,
            "correctAnswer": mapped_correct_answer,
            "alternateAnswers": alternate_answers,
            "answerInWidgetFormat": build_answer_in_widget_format(
                correct_answer,
                qid,
                lesson
            )
        })

        if blank_marker is not None:
            blank_marker.replace_with("@_@")
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
