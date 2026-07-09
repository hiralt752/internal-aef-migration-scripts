import re
from parsers.content_parser import parse_html_content
from bs4 import BeautifulSoup
from helpers.span_remover import remove_span_texts_from_html


def get_text_value(value) :
    if not value:
        return ""

    return value[0].get("text")


def extract_correct_answer_text(answer_html, question_id, lesson):
    if answer_html:
        soup = BeautifulSoup(answer_html, "html.parser")

        for blank in soup.find_all("blank"):
            blank.unwrap()

        answer_html = str(soup)

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

def map_fib_structure(raw, qid, lesson, file_path):
    body = raw.get("body", {})
    prompt = body.get("prompt", "")

    prompt = remove_span_texts_from_html( prompt, qid, lesson, file_path )

    soup = BeautifulSoup(
        prompt,
        "html.parser"
    )

    blanks = body.get(
        "blanks",
        []
    )

    blank_lookup = {
        int(blank.get("id")): blank
        for blank in blanks
        if blank.get("id") is not None
    }

    validation_lookup = {}
    answer_mapping = (
        raw.get("validation", {})
        .get("validResponse", {})
        .get("answerMapping", [])
    )

    for answer in answer_mapping:
        blank_id = answer.get("blankId")
        if blank_id is not None:
            validation_lookup[int(blank_id)] = answer

    sequential_id = 1
    items = []
    correct_answers = []

    blank_fields = soup.find_all("blank-field")

    # Normal flow: Use <blank-field> tags from HTML
    for blank in blank_fields:

        old_blank_id = int(blank.get("id"))

        blank_data = blank_lookup.get(
            old_blank_id,
            {}
        )

        validation_data = validation_lookup.get(
            old_blank_id,
            {}
        )

        correct_answer = validation_data.get("correctAnswer")
        alternate_answers = validation_data.get( "alternateAnswers", [])

        answer_type = detect_answer_type( correct_answer or "")

        feedback = blank_data.get("feedback")
        feedback_text = ""

        if feedback:
            parsed_feedback = parse_html_content(feedback, qid, lesson)
            if parsed_feedback:
                feedback_text = parsed_feedback[0]["text"]

        items.append({
            "id": sequential_id,
            "weight": normalize_weight(
                blank_data.get("weight", 100.0)
            ),
            "feedback": feedback_text,
            "rules": blank_data.get("rules", []),
            "decimalNotation": blank_data.get("decimalNotation"),
            "periodNotation": blank_data.get("periodNotation"),
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
        })

        correct_answers.append({
            "blankId": sequential_id,
            "correctAnswer": (
                extract_correct_answer_text(
                    correct_answer,
                    qid,
                    lesson
                )
                if correct_answer
                else None
            ),
            "alternateAnswers": alternate_answers,
            "answerInWidgetFormat": None
        })

        blank.replace_with("@_@")
        sequential_id += 1

    # Fallback: No <blank-field> tags found.
    # Build items from body["blanks"].
    if not items and blanks:

        for blank_data in blanks:

            old_blank_id = int(blank_data.get("id"))

            validation_data = validation_lookup.get(
                old_blank_id,
                {}
            )

            correct_answer = validation_data.get("correctAnswer")
            alternate_answers = validation_data.get(
                "alternateAnswers",
                []
            )

            answer_type = detect_answer_type(
                correct_answer or ""
            )

            feedback = blank_data.get("feedback")
            feedback_text = ""

            if feedback:
                parsed_feedback = parse_html_content(
                    feedback,
                    qid,
                    lesson
                )

                if parsed_feedback:
                    feedback_text = parsed_feedback[0]["text"]

            items.append({
                "id": sequential_id,
                "weight": normalize_weight(
                    blank_data.get("weight", 100.0)
                ),
                "feedback": feedback_text,
                "rules": blank_data.get("rules", []),
                "decimalNotation": blank_data.get("decimalNotation"),
                "periodNotation": blank_data.get("periodNotation"),
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
            })

            correct_answers.append({
                "blankId": sequential_id,
                "correctAnswer": (
                    extract_correct_answer_text(
                        correct_answer,
                        qid,
                        lesson
                    )
                    if correct_answer
                    else None
                ),
                "alternateAnswers": alternate_answers,
                "answerInWidgetFormat": None
            })

            sequential_id += 1

    # Final fallback:
    # Guarantee items is never empty.
    if not items:

        items.append({
            "id": 1,
            "weight": None,
            "feedback": None,
            "rules": [],
            "decimalNotation": None,
            "periodNotation": None,
            "answerType": None,
            "inputType": "TEXT_BLANK",
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
        })

        correct_answers.append({
            "blankId": 1,
            "correctAnswer": None,
            "alternateAnswers": [],
            "answerInWidgetFormat": None
        })

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