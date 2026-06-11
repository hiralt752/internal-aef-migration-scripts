def build_response_declaration(
    raw,
    multiple_answer=False
):

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