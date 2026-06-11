from parsers.content_parser import (
    parse_html_content
)


def map_hints_and_feedback(
    hints,
    wrong_feedback,question_id,lesson
):

    parsed_wrong = parse_html_content(
        wrong_feedback,question_id,lesson
    )

    wrong_has_text = any(
        x["type"] == "text"
        for x in parsed_wrong
    )

    if wrong_has_text:

        need_help = []

        for hint in hints:

            need_help.extend(
                parse_html_content(hint,question_id,lesson)
            )

        return {
            "incorrect": parsed_wrong,
            "needHelp": need_help
        }

    if not hints:

        return {
            "incorrect": None,
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
                "needHelp": parsed
            }

        return {
            "incorrect": parsed,
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
        "needHelp": need_help
    }