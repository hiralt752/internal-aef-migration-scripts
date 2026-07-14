import re


SCIENCE_CURRICULUM_SUBJECT = "science"
MATH_CURRICULUM_SUBJECT = "math"

CURRICULUM_SUBJECTS = {
    SCIENCE_CURRICULUM_SUBJECT,
    MATH_CURRICULUM_SUBJECT
}

MATH_CURRICULUM_MIN_GRADE = 5
MATH_CURRICULUM_MAX_GRADE = 8


def normalize_subject_for_curriculum(subject):
    subject = str(
        subject or ""
    ).strip().upper()

    if subject in [
        "SCIENCE",
        "SCIENCE_EN",
        "BIOLOGY",
        "BIOLOGY_EN",
        "CHEMISTRY",
        "CHEMISTRY_EN",
        "PHYSICS",
        "PHYSICS_EN"
    ]:
        return SCIENCE_CURRICULUM_SUBJECT

    if subject in [
        "MATH",
        "MATH_EN"
    ]:
        return MATH_CURRICULUM_SUBJECT

    return None


def curriculum_enabled_for_subject_and_grade(
    subject,
    grade
):
    normalized_subject = normalize_subject_for_curriculum(
        subject
    )

    if normalized_subject == SCIENCE_CURRICULUM_SUBJECT:
        return True

    if normalized_subject != MATH_CURRICULUM_SUBJECT:
        return False

    try:
        numeric_grade = int(grade)
    except Exception:
        return False

    return (
        MATH_CURRICULUM_MIN_GRADE
        <= numeric_grade
        <= MATH_CURRICULUM_MAX_GRADE
    )


def get_grade_window(
    grade,
    min_grade=1,
    max_grade=12
):
    try:
        grade = int(grade)

    except Exception:
        return []

    grades = [
        grade - 1,
        grade,
        grade + 1
    ]

    return [
        item
        for item in grades
        if min_grade <= item <= max_grade
    ]


def get_curriculum_grades_for_record(
    subject,
    grade,
    min_grade=1,
    max_grade=12
):
    normalized_subject = normalize_subject_for_curriculum(
        subject
    )

    try:
        numeric_grade = int(grade)
    except Exception:
        return []

    if normalized_subject == MATH_CURRICULUM_SUBJECT:
        return (
            [numeric_grade]
            if min_grade <= numeric_grade <= max_grade
            else []
        )

    return get_grade_window(
        numeric_grade,
        min_grade=min_grade,
        max_grade=max_grade
    )


def get_curriculum_candidates_for_record(
    uploaded_files,
    subject,
    grade,
    min_grade=1,
    max_grade=12
):
    normalized_subject = normalize_subject_for_curriculum(
        subject
    )

    if normalized_subject not in CURRICULUM_SUBJECTS:
        return []

    if not curriculum_enabled_for_subject_and_grade(
        subject,
        grade
    ):
        return []

    candidates = build_curriculum_file_candidates(
        uploaded_files,
        normalized_subject
    )

    if normalized_subject == MATH_CURRICULUM_SUBJECT:
        return candidates

    resolved = []
    seen_file_keys = set()

    for item_grade in get_curriculum_grades_for_record(
        subject,
        grade,
        min_grade=min_grade,
        max_grade=max_grade
    ):
        candidate = find_curriculum_file_for_grade(
            uploaded_files,
            candidates,
            normalized_subject,
            item_grade
        )

        if not candidate:
            continue

        file_key = str(
            candidate["file_key"]
        )

        if file_key in seen_file_keys:
            continue

        seen_file_keys.add(
            file_key
        )
        resolved.append(
            candidate
        )

    return resolved


def build_curriculum_file_key(
    normalized_subject,
    grade
):
    return (
        f"{normalized_subject}-curriculum-outcome-grade-{grade}"
    )


def parse_grade_range_from_key(
    file_key
):
    match = re.search(
        r"curriculum-outcome-grade-(\d+)(?:\s*-\s*(\d+))?$",
        str(file_key or ""),
        flags=re.IGNORECASE
    )

    if not match:
        return None

    start_grade = int(
        match.group(1)
    )

    end_grade = int(
        match.group(2) or start_grade
    )

    if start_grade > end_grade:
        start_grade, end_grade = end_grade, start_grade

    return start_grade, end_grade


def build_curriculum_file_candidates(
    uploaded_files,
    normalized_subject
):
    candidates = []

    prefix = (
        f"{normalized_subject}-curriculum-outcome-grade-"
    )

    for file_key, file_info in uploaded_files.items():
        normalized_key = str(
            file_key or ""
        ).strip().lower()

        if not normalized_key.startswith(prefix):
            continue

        grade_range = parse_grade_range_from_key(
            normalized_key
        )

        if not grade_range:
            continue

        candidates.append(
            {
                "file_key": file_key,
                "file_info": file_info,
                "start_grade": grade_range[0],
                "end_grade": grade_range[1]
            }
        )

    return candidates


def find_curriculum_file_for_grade(
    uploaded_files,
    candidates,
    normalized_subject,
    grade
):
    exact_file_key = build_curriculum_file_key(
        normalized_subject,
        grade
    )

    exact_file_info = uploaded_files.get(
        exact_file_key
    )

    if exact_file_info:
        return {
            "file_key": exact_file_key,
            "file_info": exact_file_info,
            "start_grade": grade,
            "end_grade": grade
        }

    for candidate in candidates:
        if (
            candidate["start_grade"]
            <= grade
            <= candidate["end_grade"]
        ):
            return candidate

    return None


def resolve_curriculum_files_for_record(
    client,
    record,
    uploaded_files,
    min_grade=1,
    max_grade=12
):
    folder_subject = (
        record.get("folder_subject")
        or record.get("subject")
    )

    normalized_subject = normalize_subject_for_curriculum(
        folder_subject
    )

    if normalized_subject not in CURRICULUM_SUBJECTS:
        return {
            "enabled": False,
            "reason": "curriculum_outcome_not_required_for_subject",
            "subject": folder_subject,
            "base_grade": record.get("grade"),
            "grade_window": [],
            "files": [],
            "missing_files": []
        }

    base_grade = record.get("grade")

    if not curriculum_enabled_for_subject_and_grade(
        folder_subject,
        base_grade
    ):
        return {
            "enabled": False,
            "reason": "curriculum_outcome_not_required_for_grade",
            "subject": folder_subject,
            "base_grade": base_grade,
            "grade_window": [],
            "files": [],
            "missing_files": []
        }

    resolved_files = []
    missing_files = []
    resolved_file_keys = set()
    if normalized_subject == MATH_CURRICULUM_SUBJECT:
        selected_candidates = get_curriculum_candidates_for_record(
            uploaded_files=uploaded_files,
            subject=folder_subject,
            grade=base_grade,
            min_grade=min_grade,
            max_grade=max_grade
        )
        grade_window = get_curriculum_grades_for_record(
            folder_subject,
            base_grade,
            min_grade=min_grade,
            max_grade=max_grade
        )

        if not selected_candidates:
            missing_files.append(
                {
                    "grade": base_grade,
                    "file_key": f"{normalized_subject}-curriculum-outcome-grade-*",
                    "status": "missing_in_uploaded_files_cache"
                }
            )
    else:
        selected_candidates = []
        grade_window = get_curriculum_grades_for_record(
            folder_subject,
            base_grade,
            min_grade=min_grade,
            max_grade=max_grade
        )

        candidates = build_curriculum_file_candidates(
            uploaded_files,
            normalized_subject
        )

        for grade in grade_window:
            expected_file_key = build_curriculum_file_key(
                normalized_subject,
                grade
            )

            candidate = find_curriculum_file_for_grade(
                uploaded_files,
                candidates,
                normalized_subject,
                grade
            )

            if not candidate:
                missing_files.append(
                    {
                        "grade": grade,
                        "file_key": expected_file_key,
                        "status": "missing_in_uploaded_files_cache"
                    }
                )
                continue

            file_key = str(
                candidate["file_key"]
            )

            if file_key in resolved_file_keys:
                for item in resolved_files:
                    if item.get("file_key") == file_key:
                        item.setdefault(
                            "grades",
                            []
                        ).append(
                            grade
                        )
                        break

                continue

            selected_candidates.append(
                candidate
            )

    for candidate in selected_candidates:
        if normalized_subject == MATH_CURRICULUM_SUBJECT:
            covered_grades = list(
                range(
                    candidate["start_grade"],
                    candidate["end_grade"] + 1
                )
            )
            grade = base_grade
        else:
            covered_grades = [
                item
                for item in grade_window
                if candidate["start_grade"] <= item <= candidate["end_grade"]
            ]
            grade = covered_grades[0] if covered_grades else base_grade

        file_key = candidate["file_key"]
        file_info = candidate["file_info"]
        grade_range = [
            candidate["start_grade"],
            candidate["end_grade"]
        ]

        if file_key in resolved_file_keys:
            continue

        try:
            gemini_file = client.files.get(
                name=file_info["gemini_file_name"]
            )

            resolved_file_keys.add(
                file_key
            )

            resolved_files.append(
                {
                    "grade": grade,
                    "grades": covered_grades or [grade],
                    "grade_range": grade_range,
                    "file_key": file_key,
                    "requested_file_key": (
                        build_curriculum_file_key(
                            normalized_subject,
                            grade
                        )
                        if normalized_subject != MATH_CURRICULUM_SUBJECT
                        else file_key
                    ),
                    "file_name": file_info.get("file_name"),
                    "gemini_file_name": file_info.get("gemini_file_name"),
                    "gemini_file": gemini_file,
                    "status": "resolved"
                }
            )

        except Exception as e:
            missing_files.append(
                {
                    "grade": grade,
                    "grade_range": grade_range,
                    "file_key": file_key,
                    "requested_file_key": (
                        build_curriculum_file_key(
                            normalized_subject,
                            grade
                        )
                        if normalized_subject != MATH_CURRICULUM_SUBJECT
                        else file_key
                    ),
                    "file_name": file_info.get("file_name"),
                    "gemini_file_name": file_info.get("gemini_file_name"),
                    "status": "gemini_file_get_failed",
                    "error_type": type(e).__name__,
                    "error_message": str(e),
                    "error_repr": repr(e)
                }
            )

    return {
        "enabled": True,
        "subject": normalized_subject,
        "base_grade": base_grade,
        "grade_window": grade_window,
        "files": resolved_files,
        "missing_files": missing_files
    }


def get_curriculum_files_for_contents(
    curriculum_result
):
    return [
        item["gemini_file"]
        for item in curriculum_result.get("files", [])
        if item.get("gemini_file") is not None
    ]


def get_curriculum_file_references_for_report(
    curriculum_result
):
    return {
        "enabled": curriculum_result.get("enabled"),
        "subject": curriculum_result.get("subject"),
        "base_grade": curriculum_result.get("base_grade"),
        "grade_window": curriculum_result.get("grade_window"),
        "files": [
            {
                "grade": item.get("grade"),
                "grades": item.get("grades"),
                "grade_range": item.get("grade_range"),
                "file_key": item.get("file_key"),
                "requested_file_key": item.get("requested_file_key"),
                "file_name": item.get("file_name"),
                "gemini_file_name": item.get("gemini_file_name"),
                "status": item.get("status")
            }
            for item in curriculum_result.get("files", [])
        ],
        "missing_files": curriculum_result.get("missing_files", [])
    }
