from parsers.content_parser import (
    parse_html_content
)

from helpers.feedback_mapper import (
    map_hints_and_feedback
)

from bs4 import BeautifulSoup
def is_bottom_image_present(html_text):
    soup = BeautifulSoup(html_text or "", "html.parser")

    elements = []

    for tag in soup.find_all(["p", "div", "span", "img"]):
        if tag.name == "img":
            elements.append("image")
        elif tag.get_text(strip=True):
            elements.append("text")

    if "text" in elements and "image" in elements:
        return elements.index("image") > elements.index("text")

    return False

def build_outcome_declaration(raw,question_id,lesson,question_type=None,fib_data=None):
    if question_type == "FIB":
        return build_fib_outcome(raw,fib_data,question_id,lesson)
    body = raw.get("body", {})

    validation = raw.get(
        "validation",
        {}
    )

    valid = validation.get(
        "validResponse",
        {}
    )

    outcome = {

        "scoringType":
            validation.get(
                "scoringType",
                "EXACT_MATCH"
            ),

        "scoring": {

            "normalizedMin": 0,

            "normalizedMax": 1,

            "defaultNormalizedValue": 0
        },

        "validResponse": {

            "correctAnswers": [

                {
                    "optionId": int(x),
                    "weight": 1
                }

                for x in valid.get(
                    "choiceIds",
                    []
                )
            ]
        }
    }

    general_feedback = (
        parse_html_content(
            body.get(
                "generalFeedback",
                ""
            ),question_id,lesson
        )
    )

    if general_feedback:

        outcome["seeWhy"] = {

            "layout": "TEXT",

            "content":
                general_feedback
        }

    feedback_mapping = (
        map_hints_and_feedback(
            body.get("hints", []),
            body.get(
                "wrongAnswerFeedback",
                ""
            ),question_id,lesson
        )
    )

    feedback = {}

    correct = body.get(
        "correctAnswerFeedback",
        ""
    )

    if correct.strip():

        feedback["correct"] = {

            "content":
                parse_html_content(
                    correct,question_id,lesson
                )
        }

    if feedback_mapping["incorrect"]:

        feedback["incorrect"] = {

            "content":
                feedback_mapping[
                    "incorrect"
                ]
        }

    partial = body.get(
        "partialAnswerFeedback",
        ""
    )

    if (
        raw.get("type")
        == "MULTIPLE_SELECTION"
        and partial.strip()
    ):

        feedback["partial"] = {

            "content":
                parse_html_content(
                    partial,question_id,lesson
                )
        }

    if feedback:

        outcome["feedback"] = (
            feedback
        )

    elif (
        raw.get("type")
        == "MULTIPLE_CHOICE"
    ):

        outcome["feedback"] = {}
    else:
        outcome["feedback"] = {}
    return outcome

def build_fib_outcome(raw, fib_data,question_id,lesson):
    body = raw.get("body", {})

    validation = raw.get(
        "validation",
        {}
    )

    outcome = {
        "scoringType": validation.get(
            "scoringType",
            "EXACT_MATCH"
        ),
        "scoring": {
            "normalizedMin": 0,
            "normalizedMax": 1,
            "defaultNormalizedValue": 0
        },
        "validation": {
            "scoringType": validation.get(
                "scoringType",
                "EXACT_MATCH"
            ),
            "validResponse": {
                "correctAnswers": fib_data["correct_answers"]
            }
        }
    }

    general_feedback = (
        parse_html_content(
            body.get(
                "generalFeedback",
                ""
            ),question_id,lesson
        )
    )

    if general_feedback:
        outcome["seeWhy"] = {
            "layout": "TEXT",
            "content": general_feedback
        }

    feedback_mapping = (
        map_hints_and_feedback(
            body.get("hints", []),
            body.get(
                "wrongAnswerFeedback",
                ""
            ),question_id,lesson
        )
    )

    if feedback_mapping["incorrect"]:
        outcome["feedback"] = {
            "incorrect": {
                "content": feedback_mapping["incorrect"]
            }
        }
    if outcome["feedback"] : outcome["feedback"]
    else : outcome["feedback"] = {}
    return outcome