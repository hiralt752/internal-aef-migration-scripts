def build_response_declaration(
    raw,
    multiple_answer=False,
    question_type=None
):
    if question_type == "FIB":
        return {
            "maxAttempts": 1,
            "multipleAnswer": multiple_answer
        }

    choices = (
        raw.get("body", {})
        .get("choices", {})
    )

    return {

        "maxAttempts": 1,

        "maxChoice":
            choices.get("maxChoice"),

        "minChoice":
            choices.get("minChoice"),

        "multipleAnswer":
            multiple_answer
    }