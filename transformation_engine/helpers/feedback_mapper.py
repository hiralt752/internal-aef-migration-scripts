from parsers.content_parser import (
    parse_html_content,
    split_html_only_feedback_content
)


def map_hints_and_feedback(
    hints,
    wrong_feedback,question_id,lesson
):

    # wrongAnswerFeedback feeds outcomeDeclaration.feedback.incorrect, which
    # is Html[] (text-only, no "table" field) - keep any table inline.
    parsed_wrong = parse_html_content(
        wrong_feedback, question_id, lesson, extract_table=False
    )

    # Any parsed content (text, image, audio, ...) counts as wrongAnswerFeedback
    # being present. Gating on "text" alone silently dropped table-only or
    # image-only feedback in favor of the hints-derived fallback below.
    wrong_has_content = bool(parsed_wrong)

    if wrong_has_content:

        incorrect_content, incorrect_audio = split_html_only_feedback_content(
            parsed_wrong, question_id, lesson
        )

        need_help = []

        for hint in hints:

            need_help.extend(
                parse_html_content(hint,question_id,lesson)
            )

        return {
            "incorrect": incorrect_content,
            "incorrect_audio": incorrect_audio,
            "needHelp": need_help
        }

    if not hints:

        return {
            "incorrect": None,
            "incorrect_audio": None,
            "needHelp": []
        }

    if len(hints) == 1:

        parsed = parse_html_content(
            hints[0],question_id,lesson
        )

        media = [
            x for x in parsed
            if x["type"] != "text"
        ]

        if media:

            return {
                "incorrect": None,
                "incorrect_audio": None,
                "needHelp": parsed
            }

        return {
            "incorrect": parsed,
            "incorrect_audio": None,
            "needHelp": []
        }

    parsed_hints = [
        parse_html_content(h,question_id,lesson)
        for h in hints
    ]

    last = parsed_hints[-1]

    incorrect = [
        x for x in last
        if x["type"] == "text"
    ]

    need_help = []

    for hint in parsed_hints[:-1]:
        need_help.extend(hint)

    need_help.extend([
        x for x in last
        if x["type"] != "text"
    ])

    return {
        "incorrect": incorrect,
        "incorrect_audio": None,
        "needHelp": need_help
    }