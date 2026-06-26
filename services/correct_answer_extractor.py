from services.html_text_extractor import html_to_text


def build_option_text_map(question):
    item_body = question.get(
        "itemBody",
        {}
    )

    options = item_body.get(
        "options",
        []
    )

    option_map = {}

    if not isinstance(options, list):
        return option_map

    for option in options:
        if not isinstance(option, dict):
            continue

        option_id = (
            option.get("optionId")
            if option.get("optionId") is not None
            else option.get("id")
        )

        text = ""

        content = option.get("content")

        if isinstance(content, list):
            parts = []

            for item in content:
                if isinstance(item, dict):
                    item_text = item.get("text")

                    if item_text:
                        parts.append(
                            html_to_text(item_text)
                        )

            text = " ".join(parts).strip()

        elif isinstance(content, dict):
            text = html_to_text(
                content.get("text", "")
            )

        elif isinstance(content, str):
            text = html_to_text(content)

        if option_id is not None:
            option_map[option_id] = text

    return option_map


def build_dropdown_option_text_map(question):
    item_body = question.get(
        "itemBody",
        {}
    )

    items = item_body.get(
        "items",
        []
    )

    option_map = {}

    if not isinstance(items, list):
        return option_map

    for item in items:
        if not isinstance(item, dict):
            continue

        dropdown_id = item.get("id")

        for option in item.get("options", []):
            option_id = option.get("id")

            content = option.get(
                "content",
                {}
            )

            text = ""

            if isinstance(content, dict):
                text = html_to_text(
                    content.get("text", "")
                )

            key = (
                dropdown_id,
                option_id
            )

            option_map[key] = text

    return option_map


def extract_mcq_correct_answers(question):
    answers = []

    option_map = build_option_text_map(
        question
    )

    valid_response = (
        question
        .get("outcomeDeclaration", {})
        .get("validResponse", {})
    )

    correct_answers = valid_response.get(
        "correctAnswers",
        []
    )

    for answer in correct_answers:
        option_id = answer.get("optionId")
        option_text = option_map.get(
            option_id,
            ""
        )

        answers.append(
            f"O{option_id}: {option_text}"
        )

    return answers


def extract_dnd_correct_answers(question):
    answers = []

    option_map = build_option_text_map(
        question
    )

    valid_response = (
        question
        .get("outcomeDeclaration", {})
        .get("validResponse", {})
    )

    correct_answers = valid_response.get(
        "correctAnswers",
        []
    )

    for answer in correct_answers:
        target_id = answer.get("targetId")
        option_ids = answer.get(
            "optionIds",
            []
        )

        for option_id in option_ids:
            option_text = option_map.get(
                option_id,
                ""
            )

            answers.append(
                f"T{target_id}=O{option_id}: {option_text}"
            )

    return answers


def extract_dropdown_correct_answers(question):
    answers = []

    option_map = build_dropdown_option_text_map(
        question
    )

    valid_response = (
        question
        .get("outcomeDeclaration", {})
        .get("validResponse", {})
    )

    correct_answers = valid_response.get(
        "correctAnswers",
        []
    )

    for answer in correct_answers:
        dropdown_id = (
            answer.get("dropDownId")
            or answer.get("dropdownId")
            or answer.get("itemId")
        )

        option_id = answer.get("optionId")

        option_text = option_map.get(
            (
                dropdown_id,
                option_id
            ),
            ""
        )

        answers.append(
            f"D{dropdown_id}=O{option_id}: {option_text}"
        )

    return answers


def extract_fib_correct_answers(question):
    answers = []

    validation = (
        question
        .get("outcomeDeclaration", {})
        .get("validation", {})
    )

    valid_response = validation.get(
        "validResponse",
        {}
    )

    correct_answers = valid_response.get(
        "correctAnswers",
        []
    )

    for answer in correct_answers:
        blank_id = answer.get("blankId")

        correct_answer = answer.get(
            "correctAnswer",
            ""
        )

        answers.append(
            f"B{blank_id}: {correct_answer}"
        )

        alternate_answers = answer.get(
            "alternateAnswers",
            []
        )

        for alternate in alternate_answers:
            answers.append(
                f"B{blank_id} alt: {alternate}"
            )

    return answers


def extract_matching_correct_answers(question):
    answers = []

    valid_response = (
        question
        .get("outcomeDeclaration", {})
        .get("validResponse", {})
    )

    correct_answers = valid_response.get(
        "correctAnswers",
        []
    )

    for answer in correct_answers:
        answers.append(str(answer))

    return answers


def extract_correct_answers(question):
    question_type = str(
        question.get("type", "")
    ).strip().upper()

    if question_type == "MULTIPLE_CHOICE":
        return extract_mcq_correct_answers(question)

    if question_type == "DND":
        return extract_dnd_correct_answers(question)

    if question_type == "DROPDOWN":
        return extract_dropdown_correct_answers(question)

    if question_type == "FILL_IN_THE_BLANK":
        return extract_fib_correct_answers(question)

    if question_type == "MATCHING":
        return extract_matching_correct_answers(question)

    return []
