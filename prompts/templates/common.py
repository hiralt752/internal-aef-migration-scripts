def clean_values(values):
    result = []
    seen = set()

    for value in values or []:
        clean_value = str(
            value
        ).strip()

        if not clean_value:
            continue

        if clean_value in seen:
            continue

        seen.add(
            clean_value
        )

        result.append(
            clean_value
        )

    return result


def compact_join(sections):
    return "\n\n".join(
        section.strip()
        for section in sections
        if section and section.strip()
    )


def format_list(title, values):
    values = clean_values(
        values
    )

    if not values:
        return ""

    lines = [f"{title}:"]

    for value in values:
        lines.append(f"- {value}")

    return "\n".join(lines)


def format_options(options):
    if not options:
        return ""

    lines = ["Options:"]

    for option in options:
        option_id = option.get("id") or option.get("option_id")
        dropdown_id = option.get("dropdown_id")
        text = str(
            option.get("text", "")
        ).strip()
        images = option.get("images", [])

        if dropdown_id is not None:
            lines.append(
                f"- D{dropdown_id}/O{option_id}: {text}"
            )
        else:
            lines.append(
                f"- O{option_id}: {text}"
            )

        for image in images:
            lines.append(
                f"  img={image.get('local_path') or image.get('url') or 'not_available'}"
            )

    return "\n".join(lines)


def format_correct_answers(correct_answers):
    correct_answers = clean_values(
        correct_answers
    )

    if not correct_answers:
        return ""

    lines = ["Correct:"]

    for answer in correct_answers:
        lines.append(f"- {answer}")

    return "\n".join(lines)


def format_images(images):
    if not images:
        return ""

    lines = ["Images attached in this order:"]

    for index, image in enumerate(
        images,
        start=1
    ):
        location = image.get(
            "location",
            "unknown"
        )
        status = image.get("status") or "unknown"

        lines.append(
            f"- Img{index}: location={location}, status={status}"
        )

    return "\n".join(lines)


def format_targets(targets):
    if not targets:
        return ""

    lines = ["Targets:"]

    for target in targets:
        target_id = (
            target.get("id")
            or target.get("target_id")
            or target.get("targetId")
        )

        position = target.get("position")

        if not position:
            lines.append(f"- T{target_id}")
            continue

        top = (
            position.get("Top")
            or position.get("top")
        )

        left = (
            position.get("Left")
            or position.get("left")
        )

        lines.append(f"- T{target_id}: top={top}, left={left}")

    return "\n".join(lines)


def build_question_header(data):
    return f"""
Question:
id={data.get("question_id", "")}
type={data.get("question_type", "")}
subType={data.get("question_sub_type", "")}
subject={data.get("subject", "")}
folderSubject={data.get("folder_subject", "")}
grade={data.get("grade", "")}
courseCode={data.get("course_code", "")}
""".strip()


def unique_question_text_sections(data):
    question_body = clean_values(
        data.get("question_body", [])
    )

    statements = clean_values(
        data.get("statements", [])
    )

    if question_body == statements:
        return [
            format_list(
                "Question Text",
                question_body
            )
        ]

    return [
        format_list(
            "Question Body",
            question_body
        ),
        format_list(
            "Statements",
            statements
        )
    ]
