VALID_BLOOM = {
    "REMEMBER",
    "UNDERSTAND",
    "APPLY",
    "ANALYZE",
    "EVALUATE",
    "CREATE"
}


VALID_DOK = {
    "DOK1",
    "DOK2",
    "DOK3"
}


VALID_DIFFICULTY = {
    "ACCESS",
    "EXPECTATION",
    "EXTENSION"
}


CURRICULUM_SUBJECTS = {
    "SCIENCE",
    "SCIENCE_EN"
}


ISLAMIC_SUBJECTS = {
    "ISLAMIC",
    "ISLAMIC_STUDIES"
}


BLOOM_ONLY_SUBJECTS = {
    "ARABIC",
    "SOCIAL",
    "SOCIAL_STUDIES"
}


def normalize_subject(subject):
    return str(
        subject or ""
    ).strip().upper()


def validate_confidence(
    value,
    field_name,
    errors
):
    if not isinstance(value, (int, float)):
        errors.append(
            f"{field_name} must be numeric."
        )
        return

    if value < 0 or value > 1:
        errors.append(
            f"{field_name} must be between 0 and 1."
        )


def validate_difficulty(response, errors):
    difficulty_level = str(
        response.get("difficultyLevel", "")
    ).strip().upper()

    if difficulty_level not in VALID_DIFFICULTY:
        errors.append(
            f"Invalid difficultyLevel value: {difficulty_level}"
        )

    if not response.get("difficultyReason"):
        errors.append(
            "difficultyReason is required."
        )


def validate_math_science_response(response):
    errors = []

    if not isinstance(response, dict):
        return {
            "valid": False,
            "errors": [
                "Response must be a JSON object."
            ]
        }

    top_outcome_keys = response.get(
        "topOutcomeKeys"
    )

    if not isinstance(top_outcome_keys, list):
        errors.append(
            "topOutcomeKeys must be a list."
        )
        top_outcome_keys = []

    if len(top_outcome_keys) != 3:
        errors.append(
            "topOutcomeKeys must contain exactly 3 outcome records."
        )

    previous_confidence = None

    for index, item in enumerate(top_outcome_keys):
        if not isinstance(item, dict):
            errors.append(
                f"topOutcomeKeys[{index}] must be an object."
            )
            continue

        expected_rank = index + 1

        if item.get("rank") != expected_rank:
            errors.append(
                f"topOutcomeKeys[{index}].rank must be {expected_rank}."
            )

        if not item.get("outcomeKey"):
            errors.append(
                f"topOutcomeKeys[{index}].outcomeKey is required."
            )

        if not item.get("reason"):
            errors.append(
                f"topOutcomeKeys[{index}].reason is required."
            )

        confidence = item.get(
            "confidence"
        )

        validate_confidence(
            confidence,
            f"topOutcomeKeys[{index}].confidence",
            errors
        )

        if isinstance(confidence, (int, float)):
            if (
                previous_confidence is not None
                and confidence > previous_confidence
            ):
                errors.append(
                    "topOutcomeKeys confidence must be sorted in descending order."
                )

            previous_confidence = confidence

    selected_outcome_key = response.get(
        "selectedOutcomeKey"
    )

    if not selected_outcome_key:
        errors.append(
            "selectedOutcomeKey is required."
        )

    if top_outcome_keys:
        first_item = top_outcome_keys[0]

        if isinstance(first_item, dict):
            first_outcome_key = first_item.get(
                "outcomeKey"
            )

            if (
                selected_outcome_key
                and first_outcome_key
                and selected_outcome_key != first_outcome_key
            ):
                errors.append(
                    "selectedOutcomeKey must match topOutcomeKeys[0].outcomeKey."
                )

    if not response.get("selectedOutcomeReason"):
        errors.append(
            "selectedOutcomeReason is required."
        )

    bloom = str(
        response.get("bloom", "")
    ).strip().upper()

    dok = str(
        response.get("dok", "")
    ).strip().upper()

    if bloom not in VALID_BLOOM:
        errors.append(
            f"Invalid bloom value: {bloom}"
        )

    if dok not in VALID_DOK:
        errors.append(
            f"Invalid dok value: {dok}"
        )

    if not response.get("bloomReason"):
        errors.append(
            "bloomReason is required."
        )

    if not response.get("dokReason"):
        errors.append(
            "dokReason is required."
        )

    validate_difficulty(
        response,
        errors
    )

    validate_confidence(
        response.get("confidence"),
        "confidence",
        errors
    )

    return {
        "valid": len(errors) == 0,
        "errors": errors
    }


def validate_general_response(
    response,
    require_dok=True,
    allowed_dok=None
):
    errors = []

    if not isinstance(response, dict):
        return {
            "valid": False,
            "errors": [
                "Response must be a JSON object."
            ]
        }

    bloom = str(
        response.get("bloom", "")
    ).strip().upper()

    if bloom not in VALID_BLOOM:
        errors.append(
            f"Invalid bloom value: {bloom}"
        )

    if not response.get("bloomReason"):
        errors.append(
            "bloomReason is required."
        )

    if require_dok:
        dok = str(
            response.get("dok", "")
        ).strip().upper()

        valid_dok = allowed_dok or VALID_DOK

        if dok not in valid_dok:
            errors.append(
                f"Invalid dok value: {dok}"
            )

        if not response.get("dokReason"):
            errors.append(
                "dokReason is required."
            )

    validate_difficulty(
        response,
        errors
    )

    validate_confidence(
        response.get("confidence"),
        "confidence",
        errors
    )

    return {
        "valid": len(errors) == 0,
        "errors": errors
    }


def validate_gemini_response(
    response,
    subject
):
    subject = normalize_subject(
        subject
    )

    if subject in CURRICULUM_SUBJECTS:
        return validate_math_science_response(
            response
        )

    if subject in BLOOM_ONLY_SUBJECTS:
        return validate_general_response(
            response,
            require_dok=False
        )

    if subject in ISLAMIC_SUBJECTS:
        return validate_general_response(
            response,
            allowed_dok={"DOK1", "DOK2"}
        )

    return validate_general_response(
        response
    )


def validate_allowed_outcome_keys(
    response,
    errors,
    allowed_outcome_keys
):
    if allowed_outcome_keys is None:
        return

    candidate_keys = [
        str(item.get("outcomeKey") or "").strip()
        for item in response.get("topOutcomeKeys", [])
        if isinstance(item, dict)
    ]

    selected_key = str(
        response.get("selectedOutcomeKey") or ""
    ).strip()

    if candidate_keys and len(candidate_keys) != len(set(candidate_keys)):
        errors.append(
            "topOutcomeKeys must contain three distinct outcome keys."
        )

    for outcome_key in [*candidate_keys, selected_key]:
        if outcome_key and outcome_key not in allowed_outcome_keys:
            errors.append(
                f"Outcome key is not in attached curriculum files: {outcome_key}"
            )


def assess_gemini_response(
    response,
    subject,
    allowed_outcome_keys=None,
    min_confidence=0.8
):
    validation = validate_gemini_response(
        response,
        subject
    )
    errors = list(
        validation.get("errors", [])
    )
    subject = normalize_subject(
        subject
    )

    if subject in CURRICULUM_SUBJECTS:
        validate_allowed_outcome_keys(
            response=response,
            errors=errors,
            allowed_outcome_keys=allowed_outcome_keys
        )

    confidence = response.get(
        "confidence"
    )
    confidence_ok = (
        isinstance(confidence, (int, float))
        and confidence >= min_confidence
    )
    retry_reasons = []

    if errors:
        retry_reasons.append(
            "invalid_response"
        )

        if any(
            "Outcome key" in error
            or "selectedOutcomeKey" in error
            or "topOutcomeKeys" in error
            for error in errors
        ):
            retry_reasons.append(
                "skill_id_not_found"
            )

    if not confidence_ok:
        retry_reasons.append(
            "low_confidence"
        )

    return {
        "valid": not errors and confidence_ok,
        "schema_valid": validation.get("valid", False),
        "errors": errors,
        "confidence": confidence,
        "confidence_ok": confidence_ok,
        "retry_reasons": retry_reasons
    }
