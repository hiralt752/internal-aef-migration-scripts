import argparse
import csv
import json
from datetime import datetime
from pathlib import Path


INPUT_DIR_NAME = "input"
LESSON_DATA_DIR_NAME = "lessonData"
REPORTS_DIR_NAME = "reports"
AUDIT_OUTPUT_DIR = Path("audit") / "migration_audits"

CSV_COLUMNS = [
    "cource code",
    "pool code",
    "question code",
    "oldQuestionId",
    "isMigrated",
    "newQuestionId",
    "isCognitiveDimensionGenerated",
    "isDOKGenerated",
    "isCurricullumGenerated",
    "reasonForNewCurriculum",
    "isDifficultyGenerated",
]

QUESTION_ID_COLUMNS = [
    "Question Id",
    "QuestionId",
    "question_id",
    "questionId",
]

COURSE_CODE_COLUMNS = [
    "course_Code",
    "Course Code",
    "courseCode",
    "course_code",
]

POOL_CODE_COLUMNS = [
    "Question Pool Name",
    "QuestionPoolName",
    "question_pool_name",
]

QUESTION_CODE_COLUMNS = [
    "Question Code",
    "QuestionCode",
    "question_code",
]

OUTPUT_FIELD_TO_GEMINI_FIELD = {
    "isCognitiveDimensionGenerated": "bloom",
    "isDOKGenerated": "dok",
    "isCurricullumGenerated": "selectedOutcomeKey",
    "reasonForNewCurriculum": "selectedOutcomeReason",
    "isDifficultyGenerated": "difficultyLevel",
}


def resolve_project_root():
    start_points = [
        Path.cwd().resolve(),
        Path(__file__).resolve().parent,
    ]

    checked = set()

    for start in start_points:
        current = start

        while True:
            if current in checked:
                break

            checked.add(current)

            markers = [
                current / INPUT_DIR_NAME,
                current / LESSON_DATA_DIR_NAME,
                current / REPORTS_DIR_NAME,
            ]

            if all(marker.exists() for marker in markers):
                return current

            if current.parent == current:
                break

            current = current.parent

    raise FileNotFoundError(
        "Project root not found. Expected input/, lessonData/, and reports/."
    )


PROJECT_ROOT = resolve_project_root()


def load_json_file(file_path):
    with open(file_path, "r", encoding="utf-8-sig") as handle:
        return json.load(handle)


def write_json_file(file_path, data):
    file_path.parent.mkdir(parents=True, exist_ok=True)

    with open(file_path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


def detect_encoding(file_path):
    with open(file_path, "rb") as handle:
        raw = handle.read(4)

    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        return "utf-16"

    if raw.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"

    encodings = [
        "utf-8-sig",
        "utf-8",
        "utf-16",
        "utf-16-le",
        "utf-16-be",
        "cp1252",
        "latin1",
    ]

    for encoding in encodings:
        try:
            with open(
                file_path,
                "r",
                encoding=encoding,
                errors="strict",
            ) as handle:
                handle.read(4096)
            return encoding
        except Exception:
            continue

    return "latin1"


def detect_delimiter(file_path, encoding):
    with open(
        file_path,
        "r",
        encoding=encoding,
        errors="replace",
        newline="",
    ) as handle:
        sample = handle.read(4096)

    if "\t" in sample:
        return "\t"

    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=["\t", ",", ";", "|"])
        return dialect.delimiter
    except Exception:
        return ","


def normalize_headers(row):
    normalized = {}

    for key, value in row.items():
        if key is None:
            continue

        normalized[str(key).replace("\ufeff", "").strip()] = value

    return normalized


def get_first_value(row, column_names):
    for column_name in column_names:
        value = row.get(column_name)

        if value is not None and str(value).strip():
            return str(value).strip()

    return ""


def get_input_question_id(record):
    return (
        record.get("metadata", {})
        .get("general", {})
        .get("externalId")
        or record.get("question_id")
        or record.get("id")
        or record.get("externalId")
    )


def collect_input_questions(input_root):
    deduped = {}

    for json_file in sorted(input_root.rglob("*.json")):
        try:
            payload = load_json_file(json_file)
        except Exception:
            continue

        if not isinstance(payload, list):
            continue

        for record in payload:
            if not isinstance(record, dict):
                continue

            question_id = str(get_input_question_id(record) or "").strip()

            if not question_id:
                continue

            entry = deduped.setdefault(
                question_id,
                {
                    "oldQuestionId": question_id,
                    "source_files": set(),
                },
            )
            entry["source_files"].add(str(json_file))

    return deduped


def load_lesson_data_index(lesson_data_root):
    index = {}

    for csv_file in sorted(lesson_data_root.glob("*.csv")):
        encoding = detect_encoding(csv_file)
        delimiter = detect_delimiter(csv_file, encoding)

        with open(
            csv_file,
            "r",
            encoding=encoding,
            errors="replace",
            newline="",
        ) as handle:
            reader = csv.DictReader(handle, delimiter=delimiter)

            for raw_row in reader:
                row = normalize_headers(raw_row)
                question_id = get_first_value(row, QUESTION_ID_COLUMNS)

                if not question_id or question_id in index:
                    continue

                index[question_id] = {
                    "cource code": get_first_value(row, COURSE_CODE_COLUMNS),
                    "pool code": get_first_value(row, POOL_CODE_COLUMNS),
                    "question code": get_first_value(row, QUESTION_CODE_COLUMNS),
                    "lesson_data_file": str(csv_file),
                }

    return index


def iter_gemini_chunk_files(reports_root):
    response_root = reports_root / "gemini_runs"

    if not response_root.exists():
        return []

    chunk_files = []

    for json_file in response_root.rglob("*_chunk_*.json"):
        parts = {part.lower() for part in json_file.parts}

        if "responses_by_subject" not in parts:
            continue

        if "success" not in parts and "failed" not in parts:
            continue

        chunk_files.append(json_file)

    return sorted(chunk_files)


def parse_json_string(value):
    if not isinstance(value, str) or not value.strip():
        return None

    try:
        return json.loads(value)
    except Exception:
        return None


def extract_result_object(payload, expected_question_id):
    if isinstance(payload, dict) and isinstance(payload.get("results"), list):
        results = payload.get("results") or []

        for result in results:
            if not isinstance(result, dict):
                continue

            result_question_id = str(
                result.get("questionId")
                or result.get("question_id")
                or ""
            ).strip()

            if result_question_id == expected_question_id:
                return result

        for result in results:
            if isinstance(result, dict):
                return result

        return None

    if isinstance(payload, dict):
        return payload

    return None


def extract_parsed_response(row):
    expected_question_id = str(
        row.get("question_id")
        or row.get("questionId")
        or ""
    ).strip()

    payload_candidates = [
        row.get("parsed_response"),
        parse_json_string(row.get("clean_response")),
        parse_json_string(row.get("raw_response")),
    ]

    for payload in payload_candidates:
        parsed = extract_result_object(payload, expected_question_id)

        if isinstance(parsed, dict):
            return parsed

    return {}


def count_present_fields(parsed_response):
    present = 0

    for source_field in OUTPUT_FIELD_TO_GEMINI_FIELD.values():
        value = parsed_response.get(source_field)

        if value is not None and str(value).strip():
            present += 1

    return present


def status_rank(status):
    if str(status).strip().lower() == "success":
        return 1

    return 0


def build_gemini_index(reports_root):
    index = {}

    for chunk_file in iter_gemini_chunk_files(reports_root):
        try:
            rows = load_json_file(chunk_file)
        except Exception:
            continue

        if not isinstance(rows, list):
            continue

        for row in rows:
            if not isinstance(row, dict):
                continue

            question_id = str(
                row.get("question_id")
                or row.get("questionId")
                or ""
            ).strip()

            if not question_id:
                continue

            parsed_response = extract_parsed_response(row)

            candidate = {
                "question_id": question_id,
                "status": str(row.get("status") or "").strip(),
                "timestamp": str(row.get("timestamp") or "").strip(),
                "run_id": str(row.get("run_id") or "").strip(),
                "response_file": str(chunk_file),
                "parsed_response": parsed_response,
                "present_field_count": count_present_fields(parsed_response),
            }

            previous = index.get(question_id)

            if previous is None:
                index[question_id] = candidate
                continue

            previous_score = (
                previous["present_field_count"],
                status_rank(previous["status"]),
                previous["timestamp"],
            )
            candidate_score = (
                candidate["present_field_count"],
                status_rank(candidate["status"]),
                candidate["timestamp"],
            )

            if candidate_score >= previous_score:
                index[question_id] = candidate

    return index


def build_audit_rows(input_questions, lesson_data_index, gemini_index):
    csv_rows = []
    missing_rows = []

    for question_id in sorted(input_questions.keys()):
        source_files = sorted(input_questions[question_id]["source_files"])
        lesson_data = lesson_data_index.get(question_id)
        gemini_data = gemini_index.get(question_id)

        reasons = []
        missing_fields = []

        if not lesson_data:
            reasons.append("lesson_data_lookup_missing")

        if not gemini_data:
            reasons.append("gemini_response_missing")

        parsed_response = {}

        if gemini_data:
            parsed_response = gemini_data.get("parsed_response") or {}

            for output_field, source_field in OUTPUT_FIELD_TO_GEMINI_FIELD.items():
                value = parsed_response.get(source_field)

                if value is None or not str(value).strip():
                    missing_fields.append(output_field)

        exclusion_reasons = [
            reason
            for reason in reasons
            if reason in {"lesson_data_lookup_missing", "gemini_response_missing"}
        ]

        if exclusion_reasons:
            missing_rows.append(
                {
                    "oldQuestionId": question_id,
                    "reasons": exclusion_reasons,
                    "missingFields": missing_fields,
                    "sourceFiles": source_files,
                    "lessonDataFound": lesson_data is not None,
                    "geminiFound": gemini_data is not None,
                    "geminiStatus": gemini_data.get("status") if gemini_data else "",
                    "geminiRunId": gemini_data.get("run_id") if gemini_data else "",
                    "geminiResponseFile": (
                        gemini_data.get("response_file") if gemini_data else ""
                    ),
                }
            )
            continue

        csv_rows.append(
            {
                "cource code": lesson_data["cource code"],
                "pool code": lesson_data["pool code"],
                "question code": lesson_data["question code"],
                "oldQuestionId": question_id,
                "isMigrated": "",
                "newQuestionId": "",
                "isCognitiveDimensionGenerated": str(
                    parsed_response.get("bloom") or ""
                ).strip(),
                "isDOKGenerated": str(parsed_response.get("dok") or "").strip(),
                "isCurricullumGenerated": str(
                    parsed_response.get("selectedOutcomeKey") or ""
                ).strip(),
                "reasonForNewCurriculum": str(
                    parsed_response.get("selectedOutcomeReason") or ""
                ).strip(),
                "isDifficultyGenerated": str(
                    parsed_response.get("difficultyLevel") or ""
                ).strip(),
            }
        )

    return csv_rows, missing_rows


def write_csv_file(file_path, rows):
    file_path.parent.mkdir(parents=True, exist_ok=True)

    with open(file_path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def create_summary(csv_rows, missing_rows, input_questions):
    return {
        "generated_at": datetime.now().isoformat(),
        "total_unique_input_questions": len(input_questions),
        "csv_row_count": len(csv_rows),
        "excluded_question_count": len(missing_rows),
    }


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Generate migration audit CSV and missing-question JSON from input, "
            "lessonData, and gemini run reports."
        )
    )
    parser.add_argument(
        "--project-root",
        default=str(PROJECT_ROOT),
        help="Project root containing input/, lessonData/, and reports/.",
    )
    args = parser.parse_args()

    project_root = Path(args.project_root).resolve()
    input_root = project_root / INPUT_DIR_NAME
    lesson_data_root = project_root / LESSON_DATA_DIR_NAME
    reports_root = project_root / REPORTS_DIR_NAME
    audit_root = project_root / AUDIT_OUTPUT_DIR

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_file = audit_root / f"migration_audit_{timestamp}.csv"
    missing_file = audit_root / f"migration_audit_missing_{timestamp}.json"
    summary_file = audit_root / f"migration_audit_summary_{timestamp}.json"

    input_questions = collect_input_questions(input_root)
    lesson_data_index = load_lesson_data_index(lesson_data_root)
    gemini_index = build_gemini_index(reports_root)
    csv_rows, missing_rows = build_audit_rows(
        input_questions,
        lesson_data_index,
        gemini_index,
    )

    write_csv_file(csv_file, csv_rows)
    write_json_file(missing_file, missing_rows)
    write_json_file(
        summary_file,
        {
            **create_summary(csv_rows, missing_rows, input_questions),
            "csv_file": str(csv_file),
            "missing_file": str(missing_file),
        },
    )

    print(f"CSV written: {csv_file}")
    print(f"Missing JSON written: {missing_file}")
    print(f"Summary JSON written: {summary_file}")
    print(f"Total unique input questions: {len(input_questions)}")
    print(f"CSV rows written: {len(csv_rows)}")
    print(f"Excluded questions: {len(missing_rows)}")


if __name__ == "__main__":
    main()
