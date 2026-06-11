def build_dnd_outcome_declaration(raw):

    body = raw.get("body", {})

    validation = raw.get(
        "validation",
        {}
    )

    # ==========================
    # Build target map
    # ==========================

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

    answer_mappings = validation.get(
        "validResponse",
        {}
    ).get(
        "answerMapping",
        []
    )

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

    return {

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
