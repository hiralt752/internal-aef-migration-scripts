from parsers.content_parser import parse_html_content
from helpers.feedback_mapper import map_hints_and_feedback
from builders.outcome_builder import build_correct_incorrect_feedback


def build_dnd_outcome_declaration(raw, question_id=None, lesson=None):

    body = raw.get("body", {})

    validation = raw.get(
        "validation",
        {}
    )

    target_map = {}

    for idx, blank in enumerate(
        body.get("blanks", []),
        start=1
    ):
        target_map[
            blank["id"]
        ] = idx

    # ==========================
    # Build option map
    # ==========================

    option_map = {}

    choice_items = body.get(
        "choices",
        {}
    ).get(
        "choiceItems",
        []
    )

    for idx, choice in enumerate(
        choice_items,
        start=1
    ):
        option_map[
            choice["id"]
        ] = idx

    # ==========================
    # Correct answers
    # ==========================

    correct_answers = []

    valid_response = validation.get(
        "validResponse"
    ) or {}
 
 
    answer_mappings = valid_response.get(
        "answerMapping"
    ) or []
 

    for mapping in answer_mappings:

        correct_answers.append({

            "targetId":
                target_map[
                    mapping["blankId"]
                ],

            "optionIds": [
                option_map[
                    mapping["choiceId"]
                ]
            ],

            "matchMode": "ALL"
        })

        if not correct_answers:
            raise ValueError("outcomeDeclaration.validResponse.correctAnswers: correctAnswers cannot be empty")

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

            "shouldAutoGraded": True,

            "correctAnswers":
                correct_answers
        }
    }

    # =========================================================
    # SEE WHY
    # =========================================================
    general_feedback = parse_html_content(
        body.get("generalFeedback", ""),
        question_id,
        lesson
    )

    if general_feedback:
        outcome["seeWhy"] = {
            "layout": "TEXT",
            "content": general_feedback
        }

    # =========================================================
    # FEEDBACK
    # =========================================================
    feedback_mapping = map_hints_and_feedback(
        body.get("hints", []),
        body.get("wrongAnswerFeedback", ""),
        question_id,
        lesson
    )

    feedback = build_correct_incorrect_feedback(
        body,
        question_id,
        lesson,
        feedback_mapping=feedback_mapping,
        include_incorrect_audio=True,
    )

    if feedback:
        outcome["feedback"] = feedback

    return outcome
