def build_dnd_outcome_declaration(raw):

    body = raw.get("body", {})

    validation = raw.get(
        "validation",
        {}
    )

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

    valid_response = validation.get(
        "validResponse"
    ) or {}
 
 
    answer_mappings = valid_response.get(
        "answerMapping"
    ) or []
 

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

        if not correct_answers:
            raise ValueError("outcomeDeclaration.validResponse.correctAnswers: correctAnswers cannot be empty")

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
