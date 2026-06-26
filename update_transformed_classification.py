import argparse
import csv
import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path


MATH_SUBJECTS = {
    "MATH",
    "MATH_EN"
}

SCIENCE_SUBJECTS = {
    "SCIENCE",
    "SCIENCE_EN"
}

SCIENCE_FAMILY_SUBJECTS = {
    "BIOLOGY",
    "BIOLOGY_EN",
    "CHEMISTRY",
    "CHEMISTRY_EN",
    "PHYSICS",
    "PHYSICS_EN",
    *SCIENCE_SUBJECTS
}


FIXED_DOK1_SUBJECTS = {
    "ARABIC",
    "SOCIAL",
    "SOCIAL_STUDIES"
}


ISLAMIC_SUBJECTS = {
    "ISLAMIC",
    "ISLAMIC_STUDIES"
}


VALID_DOK = {
    "DOK1",
    "DOK2",
    "DOK3"
}


VALID_DIFFICULTY = {
    "ACCESS": "Access",
    "EXPECTATION": "Expectation",
    "EXTENSION": "Extension"
}


REPORT_LIMIT = 100
INPUT_DIR_NAME = "input"


def resolve_project_root():
    start_points = [
        Path.cwd().resolve(),
        Path(__file__).resolve().parent
    ]

    checked = set()

    for start in start_points:
        current = start

        while True:
            if current in checked:
                break

            checked.add(current)

            markers = [
                current / "config" / "course_code_mapping.json",
                current / "curriculum",
                current / "reports"
            ]

            if all(marker.exists() for marker in markers):
                return current

            if current.parent == current:
                break

            current = current.parent

    raise FileNotFoundError(
        "Project root not found. Expected config/, curriculum/, and reports/."
    )


PROJECT_ROOT = resolve_project_root()


def load_json_file(file_path):
    with open(
        file_path,
        "r",
        encoding="utf-8-sig"
    ) as f:
        return json.load(f)


def write_json_file(file_path, data):
    with open(
        file_path,
        "w",
        encoding="utf-8"
    ) as f:
        json.dump(
            data,
            f,
            indent=2,
            ensure_ascii=False
        )
        f.write("\n")


def get_question_id(record):
    return (
        record
        .get("metadata", {})
        .get("general", {})
        .get("externalId")
        or record.get("question_id")
        or record.get("id")
        or record.get("externalId")
    )


def normalize_subject(subject):
    return str(
        subject or ""
    ).strip().upper()


def display_subject(subject):
    subject = normalize_subject(subject)

    subject_map = {
        "MATH": "Math",
        "MATH_EN": "Math",
        "SCIENCE": "Science",
        "SCIENCE_EN": "Science",
        "BIOLOGY": "Science",
        "BIOLOGY_EN": "Science",
        "CHEMISTRY": "Science",
        "CHEMISTRY_EN": "Science",
        "PHYSICS": "Science",
        "PHYSICS_EN": "Science"
    }

    return subject_map.get(
        subject,
        subject.title() if subject else ""
    )


def curriculum_name_for_subject(subject):
    subject = normalize_subject(subject)

    if subject in MATH_SUBJECTS:
        return "CCSS"

    if subject in SCIENCE_FAMILY_SUBJECTS:
        return "NGSS"

    return None


def resource_type_for_subject(subject, ai_dok):
    subject = normalize_subject(
        subject
    )

    ai_dok = str(
        ai_dok or ""
    ).strip().upper()

    if subject in FIXED_DOK1_SUBJECTS:
        return "DOK1"

    if subject in ISLAMIC_SUBJECTS:
        return "DOK2" if ai_dok == "DOK2" else "DOK1"

    if ai_dok in VALID_DOK:
        return ai_dok

    return None


def get_record_grade(record, response=None, lookup_meta=None):
    classification = (
        record
        .get("metadata", {})
        .get("classification", {})
    )

    value = (
        classification.get("grade")
        if isinstance(classification, dict)
        else None
    )

    value = (
        value
        or (lookup_meta.get("grade") if lookup_meta else None)
        or record.get("grade")
        or (
            response.get("curriculum_references", {}).get("base_grade")
            if response
            else None
        )
    )

    metadata = record.get(
        "metadata",
        {}
    )

    if value is None and isinstance(metadata, dict):
        value = (
            metadata.get("grade")
            or metadata.get("general", {}).get("grade")
        )

    return str(value) if value is not None else ""


def normalize_difficulty_level(value):
    normalized = str(
        value or ""
    ).strip().upper()

    return VALID_DIFFICULTY.get(normalized)


def get_record_subject(record, response=None, file_path=None, lookup_meta=None):
    classification = (
        record
        .get("metadata", {})
        .get("classification", {})
    )

    value = (
        classification.get("subject")
        if isinstance(classification, dict)
        else None
    )

    metadata = record.get(
        "metadata",
        {}
    )

    if value is None and isinstance(metadata, dict):
        value = (
            metadata.get("subject")
            or metadata.get("general", {}).get("subject")
        )

    value = (
        value
        or (lookup_meta.get("folder_subject") if lookup_meta else None)
        or (lookup_meta.get("subject") if lookup_meta else None)
        or record.get("folder_subject")
        or record.get("subject")
        or (response.get("subject") if response else None)
    )

    if not value and file_path:
        try:
            value = Path(file_path).parent.name
        except Exception:
            value = None

    return value or ""


def parse_outcome_key(outcome_key):
    outcome_key = str(
        outcome_key or ""
    ).strip()

    if not outcome_key:
        return "", ""

    outcome_type, separator, outcome_id = outcome_key.partition("-")

    if not separator:
        return "", outcome_key

    return outcome_type, outcome_id


def load_curriculum_index(curriculum_root):
    curriculum_root = Path(curriculum_root)
    index = {}

    for csv_file in curriculum_root.rglob("*.csv"):
        subject_folder = normalize_subject(csv_file.parent.name)

        try:
            with open(
                csv_file,
                "r",
                encoding="utf-8-sig",
                newline=""
            ) as f:
                reader = csv.DictReader(f)

                for row in reader:
                    outcome_key = str(
                        row.get("outcomeKey")
                        or row.get("outcome_key")
                        or ""
                    ).strip()

                    if not outcome_key:
                        continue

                    outcome_type, outcome_id = parse_outcome_key(
                        outcome_key
                    )

                    payload = {
                        "outcomeKey": outcome_key,
                        "type": outcome_type,
                        "id": outcome_id,
                        "name": str(row.get("code") or "").strip(),
                        "description": str(row.get("description") or "").strip(),
                        "source_file": str(csv_file),
                        "source_subject": subject_folder
                    }

                    index[outcome_key] = payload
                    index.setdefault(
                        outcome_id,
                        payload
                    )

        except Exception:
            continue

    return index


def load_question_lookup_index(question_lookup_root):
    question_lookup_root = Path(question_lookup_root)
    index = {}

    for lookup_file in question_lookup_root.rglob("question_lookup.json"):
        try:
            data = load_json_file(
                lookup_file
            )

        except Exception:
            continue

        if not isinstance(data, dict):
            continue

        for question_id, meta in data.items():
            if not isinstance(meta, dict):
                continue

            index[str(question_id)] = meta

    return index


def iter_response_chunk_files(reports_root, run_id=None):
    reports_root = Path(reports_root)

    if run_id:
        run_root = reports_root / "gemini_runs" / run_id
        return sorted(
            run_root.rglob("success/*_chunk_*.json")
        )

    return sorted(
        reports_root.rglob("success/*_chunk_*.json")
    )


def load_gemini_response_index(reports_root, run_id=None):
    index = {}

    for chunk_file in iter_response_chunk_files(
        reports_root,
        run_id=run_id
    ):
        try:
            rows = load_json_file(
                chunk_file
            )

        except Exception:
            continue

        if not isinstance(rows, list):
            continue

        for response in rows:
            if not isinstance(response, dict):
                continue

            if response.get("status") != "success":
                continue

            question_id = response.get("question_id")

            if not question_id:
                continue

            previous = index.get(
                question_id
            )

            if not previous:
                index[question_id] = response
                continue

            if str(response.get("timestamp", "")) >= str(
                previous.get("timestamp", "")
            ):
                index[question_id] = response

    return index


def selected_outcome_key(parsed_response):
    if not isinstance(parsed_response, dict):
        return ""

    selected = parsed_response.get(
        "selectedOutcomeKey"
    )

    if selected:
        return str(selected).strip()

    top_outcome_keys = parsed_response.get(
        "topOutcomeKeys",
        []
    )

    if (
        isinstance(top_outcome_keys, list)
        and
        top_outcome_keys
    ):
        first = top_outcome_keys[0]

        if isinstance(first, dict):
            return str(
                first.get("outcomeKey")
                or ""
            ).strip()

    return ""


def build_curriculum_outcome(
    outcome_key,
    subject,
    grade,
    curriculum_index
):
    if not outcome_key:
        return None, "missing_outcome_key"

    outcome_type, outcome_id = parse_outcome_key(
        outcome_key
    )

    curriculum_row = (
        curriculum_index.get(outcome_key)
        or curriculum_index.get(outcome_id)
    )

    if not curriculum_row:
        return None, "curriculum_outcome_not_found"

    curriculum = curriculum_name_for_subject(
        subject
    )

    return {
        "type": outcome_type or curriculum_row.get("type"),
        "id": outcome_id or curriculum_row.get("id"),
        "name": curriculum_row.get("name", ""),
        "description": curriculum_row.get("description", ""),
        "curriculum": curriculum,
        "grade": str(grade),
        "subject": display_subject(subject)
    }, None


def build_classification(
    record,
    response,
    curriculum_index,
    file_path,
    lookup_meta=None
):
    parsed_response = response.get(
        "parsed_response",
        {}
    )

    subject = get_record_subject(
        record,
        response=response,
        file_path=file_path,
        lookup_meta=lookup_meta
    )

    grade = get_record_grade(
        record,
        response=response,
        lookup_meta=lookup_meta
    )

    curriculum = curriculum_name_for_subject(
        subject
    )

    metadata = record.setdefault(
        "metadata",
        {}
    )

    educational = metadata.setdefault(
        "educational",
        {}
    )

    classification = metadata.get(
        "classification"
    )

    if not isinstance(classification, dict):
        classification = {}
    else:
        classification = dict(
            classification
        )

    metadata["classification"] = classification

    classification["grade"] = str(
        grade
    )
    classification["subject"] = display_subject(
        subject
    )

    if curriculum:
        classification["curriculum"] = curriculum

    bloom = parsed_response.get(
        "bloom"
    )
    ai_dok = parsed_response.get(
        "dok"
    )
    difficulty_level = normalize_difficulty_level(
        parsed_response.get("difficultyLevel")
    )

    dok = resource_type_for_subject(
        subject,
        ai_dok
    )

    if bloom:
        educational["cognitiveDimensions"] = [
            bloom
        ]

    if dok:
        educational["resourceType"] = dok

    if difficulty_level:
        educational["difficultyLevel"] = difficulty_level

    outcome_key = selected_outcome_key(
        parsed_response
    )

    curriculum_outcome, outcome_error = build_curriculum_outcome(
        outcome_key=outcome_key,
        subject=subject,
        grade=grade,
        curriculum_index=curriculum_index
    )

    if curriculum and outcome_error:
        raise ValueError(
            outcome_error
        )

    if curriculum_outcome:
        classification["curriculumOutcomes"] = [
            curriculum_outcome
        ]
    elif curriculum:
        classification.setdefault(
            "curriculumOutcomes",
            []
        )

    return classification, None


def process_file(
    file_path,
    response_index,
    curriculum_index,
    question_lookup_index,
    dry_run=False
):
    file_path = Path(file_path)

    result = {
        "file": str(file_path),
        "total_records": 0,
        "updated": 0,
        "missing_response": 0,
        "failed": 0,
        "success_question_ids": [],
        "failed_question_ids": [],
        "errors": []
    }

    try:
        data = load_json_file(
            file_path
        )

    except Exception as e:
        result["failed"] += 1
        result["errors"].append(
            {
                "question_id": None,
                "reason": "file_read_error",
                "message": str(e)
            }
        )
        return result

    is_list = isinstance(
        data,
        list
    )

    records = data if is_list else [data]

    changed = False

    for record in records:
        if not isinstance(record, dict):
            continue

        result["total_records"] += 1

        question_id = get_question_id(
            record
        )

        if not question_id:
            result["failed"] += 1
            result["failed_question_ids"].append(
                None
            )
            result["errors"].append(
                {
                    "question_id": None,
                    "reason": "missing_question_id"
                }
            )
            continue

        response = response_index.get(
            question_id
        )

        if not response:
            result["missing_response"] += 1
            continue

        try:
            lookup_meta = question_lookup_index.get(
                question_id,
                {}
            )

            classification, outcome_error = build_classification(
                record=record,
                response=response,
                curriculum_index=curriculum_index,
                file_path=file_path,
                lookup_meta=lookup_meta
            )

            changed = True
            result["updated"] += 1
            result["success_question_ids"].append(
                question_id
            )

            if outcome_error:
                result["errors"].append(
                    {
                        "question_id": question_id,
                        "reason": outcome_error
                    }
                )

        except Exception as e:
            result["failed"] += 1
            result["failed_question_ids"].append(
                question_id
            )
            result["errors"].append(
                {
                    "question_id": question_id,
                    "reason": "record_update_error",
                    "message": str(e)
                }
            )

    if changed and not dry_run:
        write_json_file(
            file_path,
            data
        )

    return result


def collect_json_files(paths):
    files = []

    for item in paths:
        path = Path(item)

        if not path.is_absolute():
            path = PROJECT_ROOT / path

        if path.is_file() and path.suffix.lower() == ".json":
            files.append(
                path
            )
            continue

        if path.is_dir():
            files.extend(
                sorted(
                    path.rglob("*.json")
                )
            )

    unique = []
    seen = set()

    for file_path in files:
        resolved = str(
            file_path.resolve()
        )

        if resolved in seen:
            continue

        seen.add(
            resolved
        )
        unique.append(
            Path(resolved)
        )

    return unique


def write_reports(report_dir, results, started_at, dry_run):
    report_dir = Path(report_dir)
    report_dir.mkdir(
        parents=True,
        exist_ok=True
    )

    success_ids = []
    failed_ids = []
    errors = []

    for result in results:
        success_ids.extend(
            result.get("success_question_ids", [])
        )
        failed_ids.extend(
            [
                question_id
                for question_id in result.get("failed_question_ids", [])
                if question_id
            ]
        )

        for error in result.get("errors", []):
            error_payload = {
                **error,
                "file": result.get("file")
            }
            errors.append(
                error_payload
            )

    success_ids = sorted(
        set(success_ids)
    )
    failed_ids = sorted(
        set(failed_ids)
    )

    summary = {
        "started_at": started_at,
        "ended_at": datetime.now().isoformat(),
        "dry_run": dry_run,
        "files_processed": len(results),
        "records_seen": sum(item.get("total_records", 0) for item in results),
        "records_updated": sum(item.get("updated", 0) for item in results),
        "missing_response": sum(item.get("missing_response", 0) for item in results),
        "failed": sum(item.get("failed", 0) for item in results),
        "success_count": len(success_ids),
        "failed_count": len(failed_ids),
        "error_count": len(errors)
    }

    write_json_file(
        report_dir / "summary.json",
        summary
    )

    write_json_file(
        report_dir / "success_question_ids.json",
        success_ids
    )

    write_json_file(
        report_dir / "failed_question_ids.json",
        failed_ids
    )

    write_json_file(
        report_dir / "errors.json",
        errors[:REPORT_LIMIT]
    )

    return summary


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Update transformed question classification blocks from "
            "stored Gemini responses."
        )
    )

    parser.add_argument(
        "paths",
        nargs="*",
        default=[INPUT_DIR_NAME],
        help="JSON files or folders to update."
    )

    parser.add_argument(
        "--reports-root",
        default=str(PROJECT_ROOT / "reports"),
        help="Reports root containing gemini_runs."
    )

    parser.add_argument(
        "--run-id",
        default=None,
        help="Optional Gemini run id. Defaults to all runs, latest response wins."
    )

    parser.add_argument(
        "--curriculum-root",
        default=str(PROJECT_ROOT / "curriculum"),
        help="Curriculum CSV root."
    )

    parser.add_argument(
        "--question-lookup-root",
        default=str(PROJECT_ROOT / "output" / "question_lookup"),
        help="Question lookup root containing subject/grade metadata."
    )

    parser.add_argument(
        "--workers",
        type=int,
        default=max(
            1,
            min(
                8,
                (os.cpu_count() or 2)
            )
        ),
        help="Number of worker threads."
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Build reports without writing transformed JSON files."
    )

    parser.add_argument(
        "--report-dir",
        default=None,
        help="Output report folder. Defaults to reports/classification_update/<timestamp>."
    )

    return parser.parse_args()


def main():
    args = parse_args()
    started_at = datetime.now().isoformat()
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")

    report_dir = (
        Path(args.report_dir)
        if args.report_dir
        else PROJECT_ROOT / "reports" / "classification_update" / run_id
    )

    json_files = collect_json_files(
        args.paths
    )

    print(
        f"Project root      : {PROJECT_ROOT}",
        flush=True
    )
    print(
        f"JSON files        : {len(json_files)}",
        flush=True
    )
    print(
        f"Workers           : {args.workers}",
        flush=True
    )
    print(
        f"Dry run           : {args.dry_run}",
        flush=True
    )
    print(
        f"Report dir        : {report_dir}",
        flush=True
    )

    curriculum_index = load_curriculum_index(
        args.curriculum_root
    )

    question_lookup_index = load_question_lookup_index(
        args.question_lookup_root
    )

    response_index = load_gemini_response_index(
        args.reports_root,
        run_id=args.run_id
    )

    print(
        f"Curriculum rows   : {len(curriculum_index)}",
        flush=True
    )
    print(
        f"Question lookups  : {len(question_lookup_index)}",
        flush=True
    )
    print(
        f"Gemini responses  : {len(response_index)}",
        flush=True
    )

    progress_lock = threading.Lock()
    completed_files = 0
    results = []

    with ThreadPoolExecutor(
        max_workers=max(1, args.workers)
    ) as executor:
        futures = [
            executor.submit(
                process_file,
                file_path,
                response_index,
                curriculum_index,
                question_lookup_index,
                args.dry_run
            )
            for file_path in json_files
        ]

        for future in as_completed(
            futures
        ):
            result = future.result()
            results.append(
                result
            )

            with progress_lock:
                completed_files += 1

                if (
                    completed_files == len(json_files)
                    or completed_files % 10 == 0
                ):
                    print(
                        f"[PROGRESS] files={completed_files}/{len(json_files)} "
                        f"updated={sum(item.get('updated', 0) for item in results)} "
                        f"missing_response={sum(item.get('missing_response', 0) for item in results)} "
                        f"failed={sum(item.get('failed', 0) for item in results)}",
                        flush=True
                    )

    summary = write_reports(
        report_dir=report_dir,
        results=results,
        started_at=started_at,
        dry_run=args.dry_run
    )

    print(
        "\nClassification update complete.",
        flush=True
    )
    print(
        json.dumps(
            summary,
            indent=2,
            ensure_ascii=False
        ),
        flush=True
    )


if __name__ == "__main__":
    main()
