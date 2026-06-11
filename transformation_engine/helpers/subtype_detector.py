from parsers.content_parser import parse_html_content


def detect_subtype(choice_items,question_id,lesson):

    has_text = False
    has_image = False

    for choice in choice_items:

        parsed = parse_html_content(
            choice.get("answer", ""),question_id,lesson
        )

        for item in parsed:

            if item["type"] == "text":
                has_text = True

            if item["type"] == "image":
                has_image = True

    if has_image and has_text:
        return "IMAGE_TEXT"

    if has_image:
        return "IMAGE"

    return "TEXT"