import csv
import hashlib
import json
from pathlib import Path

from prompts.base_prompt import BASE_CLASSIFICATION_PROMPT
from prompts.bloom_rules import BLOOM_RULES
from prompts.difficulty_rules import DIFFICULTY_RULES
from prompts.dok_rules import DOK_RULES, ISLAMIC_DOK_RULES
from services.curriculum_file_resolver import (
    CURRICULUM_SUBJECTS,
    build_curriculum_file_candidates,
    find_curriculum_file_for_grade,
    get_grade_window,
    normalize_subject_for_curriculum
)
from services.lesson_context_resolver import (
    get_record_lo_id
)
from services.prompt_builder import (
    BLOOM_ONLY_SUBJECTS,
    CURRICULUM_SUBJECTS as PROMPT_CURRICULUM_SUBJECTS,
    ISLAMIC_SUBJECTS,
    build_question_prompt
)
from services.response_validator import assess_gemini_response


USAGE_FIELDS = (
    "estimated_prompt_tokens",
    "prompt_token_count",
    "candidates_token_count",
    "thoughts_token_count",
    "cached_content_token_count",
    "total_token_count"
)


def normalize_subject(subject):
    return str(
        subject or "UNKNOWN"
    ).strip().upper()


def get_record_data(record):
    normalized = record.get(
        "normalized_input"
    )

    if isinstance(normalized, dict):
        return normalized

    return record


def get_record_question_id(record):
    data = get_record_data(
        record
    )

    return str(
        record.get("question_id")
        or data.get("question_id")
        or record.get("id")
        or ""
    ).strip()


def get_record_subject(record):
    data = get_record_data(
        record
    )

    return normalize_subject(
        record.get("folder_subject")
        or data.get("folder_subject")
        or record.get("subject")
        or data.get("subject")
    )


def get_record_grade(record):
    data = get_record_data(
        record
    )

    return (
        record.get("grade")
        if record.get("grade") is not None
        else data.get("grade")
    )


def curriculum_signature_for_record(
    record,
    uploaded_files,
    min_grade=1,
    max_grade=12
):
    subject = get_record_subject(
        record
    )

    normalized_subject = normalize_subject_for_curriculum(
        subject
    )

    if normalized_subject not in CURRICULUM_SUBJECTS:
        return (), ()

    candidates = build_curriculum_file_candidates(
        uploaded_files,
        normalized_subject
    )

    resolved_keys = []
    missing_keys = []

    for grade in get_grade_window(
        get_record_grade(record),
        min_grade=min_grade,
        max_grade=max_grade
    ):
        candidate = find_curriculum_file_for_grade(
            uploaded_files,
            candidates,
            normalized_subject,
            grade
        )

        if not candidate:
            missing_keys.append(
                f"{normalized_subject}-curriculum-outcome-grade-{grade}"
            )
            continue

        file_key = str(
            candidate["file_key"]
        )

        if file_key not in resolved_keys:
            resolved_keys.append(
                file_key
            )

    return tuple(resolved_keys), tuple(missing_keys)


def batch_group_key(record, uploaded_files):
    subject = get_record_subject(
        record
    )
    lo_id = get_record_lo_id(record)

    curriculum_signature, missing_signature = curriculum_signature_for_record(
        record,
        uploaded_files
    )

    return (
        lo_id,
        subject,
        get_record_grade(record),
        get_record_data(record).get("course_code") or record.get("course_code"),
        curriculum_signature,
        missing_signature
    )


def _list_count(value):
    return len(value) if isinstance(value, list) else 0


def build_content_manifest(record):
    data = get_record_data(
        record
    )

    question_id = get_record_question_id(
        record
    )

    images = data.get("images", [])
    images = images if isinstance(images, list) else []

    text_values = []

    for field in (
        "question_body",
        "statements",
        "options",
        "word_bank",
        "targets",
        "correct_answers",
        "hints",
        "feedback"
    ):
        value = data.get(field)

        if isinstance(value, list):
            text_values.extend(
                value
            )
        elif value:
            text_values.append(
                value
            )

    serialized_text = json.dumps(
        text_values,
        ensure_ascii=False,
        sort_keys=True,
        default=str
    )

    resolved_images = sum(
        1
        for image in images
        if isinstance(image, dict)
        and image.get("exists") is True
        and image.get("local_path")
    )

    errors = []
    warnings = []

    if not question_id:
        errors.append(
            "missing_question_id"
        )

    if not serialized_text.strip("[]\" ") and resolved_images == 0:
        errors.append(
            "question_has_no_text_or_resolved_image"
        )

    if _list_count(data.get("correct_answers")) == 0:
        warnings.append(
            "correct_answers_missing"
        )

    if len(images) != resolved_images:
        warnings.append(
            "one_or_more_images_unresolved"
        )

    content_hash = hashlib.sha256(
        json.dumps(
            data,
            ensure_ascii=False,
            sort_keys=True,
            default=str
        ).encode("utf-8")
    ).hexdigest()

    return {
        "question_id": question_id,
        "lo_id": get_record_lo_id(record),
        "lo_id_mapping_found": get_record_lo_id(record) is not None,
        "subject": get_record_subject(record),
        "grade": get_record_grade(record),
        "question_type": data.get("question_type"),
        "counts": {
            "question_body": _list_count(data.get("question_body")),
            "statements": _list_count(data.get("statements")),
            "options": _list_count(data.get("options")),
            "word_bank": _list_count(data.get("word_bank")),
            "targets": _list_count(data.get("targets")),
            "correct_answers": _list_count(data.get("correct_answers")),
            "images_expected": len(images),
            "images_resolved": resolved_images,
            "hints": _list_count(data.get("hints")),
            "feedback": _list_count(data.get("feedback"))
        },
        "content_sha256": content_hash,
        "valid": not errors,
        "errors": errors,
        "warnings": warnings
    }


def _record_estimated_text_tokens(record):
    question_prompt = build_question_prompt(
        get_record_data(record)
    )

    return max(
        1,
        (len(question_prompt) + 3) // 4
    )


def _record_image_count(record):
    images = get_record_data(record).get(
        "images",
        []
    )

    return len(images) if isinstance(images, list) else 0


def build_batches(
    records,
    uploaded_files,
    max_questions=10,
    max_images=20,
    max_estimated_text_tokens=20000
):
    grouped = {}

    for record in records:
        key = batch_group_key(
            record,
            uploaded_files
        )

        grouped.setdefault(
            key,
            []
        ).append(
            record
        )

    batches = []

    for key, group_records in grouped.items():
        current = []
        current_images = 0
        current_tokens = 0

        for record in group_records:
            record_images = _record_image_count(
                record
            )
            record_tokens = _record_estimated_text_tokens(
                record
            )

            exceeds_limit = (
                current
                and (
                    len(current) >= max_questions
                    or current_images + record_images > max_images
                    or current_tokens + record_tokens > max_estimated_text_tokens
                )
            )

            if exceeds_limit:
                batches.append(
                    {
                        "group_key": key,
                        "records": current,
                        "estimated_text_tokens": current_tokens,
                        "image_count": current_images
                    }
                )

                current = []
                current_images = 0
                current_tokens = 0

            current.append(
                record
            )
            current_images += record_images
            current_tokens += record_tokens

        if current:
            batches.append(
                {
                    "group_key": key,
                    "records": current,
                    "estimated_text_tokens": current_tokens,
                    "image_count": current_images
                }
            )

    return batches


def _batch_result_schema(subject):
    subject = normalize_subject(
        subject
    )

    if subject in PROMPT_CURRICULUM_SUBJECTS:
        return """
Each result must contain:
{
  "questionId": "exact input id",
  "topOutcomeKeys": [
    {"rank": 1, "outcomeKey": "skill-id", "confidence": 0.95, "reason": "20 words maximum"},
    {"rank": 2, "outcomeKey": "skill-id", "confidence": 0.85, "reason": "20 words maximum"},
    {"rank": 3, "outcomeKey": "skill-id", "confidence": 0.75, "reason": "20 words maximum"}
  ],
  "selectedOutcomeKey": "same as rank 1",
  "selectedOutcomeReason": "30 words maximum",
  "bloom": "APPLY",
  "bloomReason": "20 words maximum",
  "dok": "DOK2",
  "dokReason": "20 words maximum",
  "difficultyLevel": "Expectation",
  "difficultyReason": "20 words maximum",
  "confidence": 0.95
}
Use exactly three outcome keys from the attached curriculum files. Rank confidence in descending order.
""".strip()

    if subject in BLOOM_ONLY_SUBJECTS:
        return """
Each result must contain only:
{
  "questionId": "exact input id",
  "bloom": "UNDERSTAND",
  "bloomReason": "20 words maximum",
  "difficultyLevel": "Expectation",
  "difficultyReason": "20 words maximum",
  "confidence": 0.95
}
Do not return dok or dokReason. DOK is assigned deterministically later.
""".strip()

    if subject in ISLAMIC_SUBJECTS:
        return """
Each result must contain:
{
  "questionId": "exact input id",
  "bloom": "UNDERSTAND",
  "bloomReason": "20 words maximum",
  "dok": "DOK1",
  "dokReason": "20 words maximum",
  "difficultyLevel": "Expectation",
  "difficultyReason": "20 words maximum",
  "confidence": 0.95
}
Default to DOK1. DOK2 is allowed only for a clear non-foundational application or explanation. DOK3 is forbidden.
""".strip()

    return """
Each result must contain:
{
  "questionId": "exact input id",
  "bloom": "UNDERSTAND",
  "bloomReason": "20 words maximum",
  "dok": "DOK1",
  "dokReason": "20 words maximum",
  "difficultyLevel": "Expectation",
  "difficultyReason": "20 words maximum",
  "confidence": 0.95
}
""".strip()


def build_batch_instruction(subject, expected_question_ids):
    subject = normalize_subject(
        subject
    )

    parts = [
        BASE_CLASSIFICATION_PROMPT.strip(),
        "Classify every question independently. Never use one question as evidence for another.",
        "If shared lesson content is supplied for the batch, use it only as context for difficultyLevel classification for each question.",
        "Return one valid JSON object only, with this top-level shape: {\"results\": [...]}",
        "Return exactly one result for every expected questionId. Do not omit, duplicate, rename, or invent IDs.",
        f"Expected questionIds: {json.dumps(expected_question_ids, ensure_ascii=False)}",
        BLOOM_RULES.strip(),
        DIFFICULTY_RULES.strip()
    ]

    if subject in ISLAMIC_SUBJECTS:
        parts.append(
            ISLAMIC_DOK_RULES.strip()
        )
    elif subject not in BLOOM_ONLY_SUBJECTS:
        parts.append(
            DOK_RULES.strip()
        )

    parts.append(
        _batch_result_schema(subject)
    )

    return "\n\n".join(
        parts
    )


def build_question_text(record):
    question_id = get_record_question_id(
        record
    )

    question_prompt = build_question_prompt(
        get_record_data(record)
    ).replace(
        " Return JSON only.",
        ""
    )

    return "\n".join(
        [
            f"BEGIN QUESTION {question_id}",
            question_prompt,
            f"END QUESTION TEXT {question_id}"
        ]
    )


def reconcile_batch_response(
    parsed_response,
    records,
    allowed_outcome_keys=None,
    min_confidence=0.8
):
    expected = {
        get_record_question_id(record): record
        for record in records
    }

    errors = []
    valid_results = {}
    invalid_results = {}
    unexpected_ids = []
    duplicate_ids = []

    if not isinstance(parsed_response, dict):
        return {
            "valid": False,
            "errors": ["Batch response must be a JSON object."],
            "valid_results": {},
            "invalid_results": {},
            "missing_ids": sorted(expected),
            "unexpected_ids": [],
            "duplicate_ids": []
        }

    results = parsed_response.get(
        "results"
    )

    if not isinstance(results, list):
        return {
            "valid": False,
            "errors": ["results must be an array."],
            "valid_results": {},
            "invalid_results": {},
            "missing_ids": sorted(expected),
            "unexpected_ids": [],
            "duplicate_ids": []
        }

    seen = set()

    for result in results:
        if not isinstance(result, dict):
            errors.append(
                "Every results item must be an object."
            )
            continue

        question_id = str(
            result.get("questionId")
            or result.get("question_id")
            or ""
        ).strip()

        if question_id in seen:
            duplicate_ids.append(
                question_id
            )
            continue

        seen.add(
            question_id
        )

        if question_id not in expected:
            unexpected_ids.append(
                question_id
            )
            continue

        per_question = dict(
            result
        )
        per_question.pop(
            "questionId",
            None
        )
        per_question.pop(
            "question_id",
            None
        )

        subject = get_record_subject(
            expected[question_id]
        )

        validation = assess_gemini_response(
            response=per_question,
            subject=subject,
            allowed_outcome_keys=(
                allowed_outcome_keys
                if subject in PROMPT_CURRICULUM_SUBJECTS
                else None
            ),
            min_confidence=min_confidence
        )

        if validation["valid"]:
            valid_results[question_id] = {
                "parsed_response": per_question,
                "validation": validation
            }
        else:
            invalid_results[question_id] = {
                "parsed_response": per_question,
                "validation": validation
            }

    missing_ids = sorted(
        set(expected) - seen
    )

    for duplicate_id in duplicate_ids:
        if duplicate_id not in expected:
            continue

        existing = valid_results.pop(
            duplicate_id,
            None
        ) or invalid_results.get(
            duplicate_id
        )

        invalid_results[duplicate_id] = {
            "parsed_response": (
                existing.get("parsed_response", {})
                if existing
                else {}
            ),
            "validation": {
                "valid": False,
                "errors": [
                    "Question ID appears more than once in batch results."
                ]
            }
        }

    if missing_ids:
        errors.append(
            f"Missing question IDs: {missing_ids}"
        )

    if unexpected_ids:
        errors.append(
            f"Unexpected question IDs: {unexpected_ids}"
        )

    if duplicate_ids:
        errors.append(
            f"Duplicate question IDs: {duplicate_ids}"
        )

    if invalid_results:
        errors.append(
            f"Invalid results: {sorted(invalid_results)}"
        )

    return {
        "valid": not errors,
        "errors": errors,
        "valid_results": valid_results,
        "invalid_results": invalid_results,
        "missing_ids": missing_ids,
        "unexpected_ids": unexpected_ids,
        "duplicate_ids": duplicate_ids
    }


def load_allowed_outcome_keys(
    project_root,
    curriculum_references,
    uploaded_files,
    cache=None
):
    cache = cache if cache is not None else {}
    file_keys = tuple(
        sorted(
            str(item.get("file_key"))
            for item in curriculum_references.get("files", [])
            if item.get("file_key")
        )
    )

    if file_keys in cache:
        return cache[file_keys]

    outcome_keys = set()

    for file_key in file_keys:
        file_info = uploaded_files.get(
            file_key,
            {}
        )

        file_path = file_info.get(
            "file_path"
        )

        if not file_path:
            continue

        path = Path(
            file_path
        )

        if not path.is_absolute():
            path = Path(project_root) / path

        try:
            with open(
                path,
                "r",
                encoding="utf-8-sig",
                newline=""
            ) as handle:
                for row in csv.DictReader(handle):
                    outcome_key = str(
                        row.get("outcomeKey")
                        or row.get("outcome_key")
                        or ""
                    ).strip()

                    if outcome_key:
                        outcome_keys.add(
                            outcome_key
                        )
        except Exception:
            continue

    cache[file_keys] = outcome_keys

    return outcome_keys


def empty_usage():
    return {
        field: 0
        for field in USAGE_FIELDS
    }


def add_usage(total, addition):
    result = dict(
        total or empty_usage()
    )

    for field in USAGE_FIELDS:
        result[field] = int(
            result.get(field) or 0
        ) + int(
            (addition or {}).get(field) or 0
        )

    return result


def distribute_usage(usage, question_ids):
    question_ids = list(
        question_ids
    )

    if not question_ids:
        return {}

    distributed = {
        question_id: empty_usage()
        for question_id in question_ids
    }

    for field in USAGE_FIELDS:
        value = int(
            (usage or {}).get(field) or 0
        )

        quotient, remainder = divmod(
            value,
            len(question_ids)
        )

        for index, question_id in enumerate(question_ids):
            distributed[question_id][field] = (
                quotient
                + (1 if index < remainder else 0)
            )

    return distributed
