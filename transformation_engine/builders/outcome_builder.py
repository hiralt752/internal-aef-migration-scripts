from parsers.content_parser import parse_html_content, split_html_only_feedback_content
from helpers.feedback_mapper import map_hints_and_feedback
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


def _placeholder_feedback(text):
    return {"content": [{"type": "text", "text": text}]}


def _feedback_content(items, question_id=None, lesson=None):
    content, audio = split_html_only_feedback_content(items, question_id, lesson)
    result = {"content": content}
    if audio:
        result["audio"] = audio
    return result


def _has_feedback_text(entry):
    """An image/audio-only feedback entry satisfies the JSON schema (its
    items still carry text="") but is functionally blank - the API's "correct
    and incorrect feedback are required when seeWhy is present" check rejects
    it just the same as a missing key, so callers must hard-code a fallback
    for both cases alike."""
    if not entry:
        return False
    return any((item.get("text") or "").strip() for item in entry.get("content", []))


def build_correct_feedback(correct_html, question_id=None, lesson=None):
    """Build outcomeDeclaration.feedback.correct from a correctAnswerFeedback
    HTML string, the same way MCQ does. Returns None when there is no source
    text to parse."""
    correct_html = correct_html or ""
    if not correct_html.strip():
        return None

    correct_items = parse_html_content(
        correct_html, question_id, lesson, extract_table=False
    )
    return _feedback_content(correct_items, question_id, lesson)


def build_correct_incorrect_feedback(
    body,
    question_id,
    lesson,
    feedback_mapping=None,
    include_incorrect_audio=False,
):
    """Build outcomeDeclaration.feedback's "correct" and "incorrect" entries
    the same way MCQ does: correctAnswerFeedback -> "correct",
    wrongAnswerFeedback/hints (via map_hints_and_feedback) -> "incorrect",
    with a hard-coded placeholder for whichever side has no real text."""
    if feedback_mapping is None:
        feedback_mapping = map_hints_and_feedback(
            body.get("hints", []),
            body.get("wrongAnswerFeedback", ""),
            question_id,
            lesson
        )

    feedback = {}

    correct_feedback = build_correct_feedback(
        body.get("correctAnswerFeedback", ""), question_id, lesson
    )
    if correct_feedback:
        feedback["correct"] = correct_feedback

    if feedback_mapping.get("incorrect"):
        feedback["incorrect"] = {"content": feedback_mapping["incorrect"]}
        if include_incorrect_audio and feedback_mapping.get("incorrect_audio"):
            feedback["incorrect"]["audio"] = feedback_mapping["incorrect_audio"]

    if not _has_feedback_text(feedback.get("correct")):
        feedback["correct"] = _placeholder_feedback("correct")
    if not _has_feedback_text(feedback.get("incorrect")):
        feedback["incorrect"] = _placeholder_feedback("incorrect")

    return feedback


def build_outcome_declaration(raw, question_id, lesson, question_type=None, fib_data=None):

    if question_type == "FIB":
        return build_fib_outcome(raw, fib_data, question_id, lesson)

    body = raw.get("body", {})
    validation = raw.get("validation", {})
    valid = validation.get("validResponse", {})

    # =========================================================
    # IMAGE LABELLING DRAG DROP FIXED
    # =========================================================
    if question_type == "IMAGE_LABELLING_DRAG_DROP":

        blanks = body.get("blanks", [])
        choices = body.get("choices", {}).get("choiceItems", [])

        blank_index_map = {
            b["id"]: idx + 1
            for idx, b in enumerate(blanks)
        }

        choice_index_map = {
            c["id"]: idx + 1
            for idx, c in enumerate(choices)
        }

        mappings = valid.get("answerMapping", [])

        correct_answers = []

        for m in mappings:

            blank_aat_id = m["blankId"]
            choice_aat_id = m["choiceId"]

            target_id = blank_index_map.get(blank_aat_id)
            option_id = choice_index_map.get(choice_aat_id)

            if target_id is None or option_id is None:
                continue

            correct_answers.append({
                "targetId": target_id,
                "optionIds": [option_id],
                "matchMode": "ALL"
            })

    # =========================================================
    # DEFAULT MCQ / MSQ LOGIC
    # =========================================================
    else:

        choice_ids = valid.get("choiceIds", [])

        correct_answers = [
            {
                "optionId": int(x),
                "weight": 1
            }
            for x in choice_ids
        ]

    # =========================================================
    # OUTCOME STRUCTURE
    # =========================================================
    outcome = {
        "scoringType": validation.get("scoringType", "EXACT_MATCH"),
        "scoring": {
            "normalizedMin": 0,
            "normalizedMax": 1,
            "defaultNormalizedValue": 0
        },
        "validResponse": {
            "correctAnswers": correct_answers
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
        body, question_id, lesson, feedback_mapping=feedback_mapping
    )

    partial = body.get("partialAnswerFeedback", "")
    if (
        raw.get("type") == "MULTIPLE_SELECTION"
        and partial.strip()
    ):
        partial_items = parse_html_content(partial, question_id, lesson, extract_table=False)
        feedback["partial"] = _feedback_content(partial_items, question_id, lesson)

    if feedback:
        outcome["feedback"] = feedback

    return outcome


def build_fib_outcome(raw, fib_data, question_id, lesson):
    body = raw.get("body", {})
    validation = raw.get("validation", {})

    outcome = {
        "scoringType": validation.get("scoringType", "EXACT_MATCH"),
        "scoring": {
            "normalizedMin": 0,
            "normalizedMax": 1,
            "defaultNormalizedValue": 0
        },
        "validation": {
            "scoringType": validation.get("scoringType", "EXACT_MATCH"),
            "validResponse": {
                "correctAnswers": fib_data["correct_answers"]
            }
        }
    }

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
