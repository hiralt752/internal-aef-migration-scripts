from parsers.content_parser import parse_html_content


def detect_subtype(choice_items,question_id,lesson):

    has_text = False
    total_image_count = 0

    for choice in choice_items:

        parsed = parse_html_content(
            choice.get("answer", ""),question_id,lesson
        )

        for item in parsed:

            if item["type"] == "text":
                has_text = True

            if item["type"] == "image":
                total_image_count += 1

    # More than one image across the options (e.g. one image per option)
    # renders as an image grid alongside text, not a single hero image, so
    # it needs IMAGE_TEXT rather than IMAGE.
    if total_image_count > 1:
        return "IMAGE_TEXT"

    if total_image_count == 1 and has_text:
        return "IMAGE_TEXT"

    if total_image_count == 1:
        return "IMAGE"

    return "TEXT"
