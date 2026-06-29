import re


CURRICULUM_SUBJECTS = {
    "science"
}


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
        return "science"

    return None


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

    grade_window = get_grade_window(
        base_grade,
        min_grade=min_grade,
        max_grade=max_grade
    )

    resolved_files = []
    missing_files = []
    resolved_file_keys = set()
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

        file_key = candidate["file_key"]
        file_info = candidate["file_info"]
        grade_range = [
            candidate["start_grade"],
            candidate["end_grade"]
        ]

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
                    "grades": [
                        grade
                    ],
                    "grade_range": grade_range,
                    "file_key": file_key,
                    "requested_file_key": expected_file_key,
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
                    "requested_file_key": expected_file_key,
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
