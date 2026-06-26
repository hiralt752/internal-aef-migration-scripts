import csv
import json
from pathlib import Path
from collections import defaultdict
from datetime import datetime


QUESTION_ID_COLUMNS = [
    "Question Id",
    "QuestionId",
    "question_id",
    "questionId"
]

COURSE_CODE_COLUMNS = [
    "course_Code",
    "Course Code",
    "courseCode",
    "course_code"
]

SUBJECT_COLUMNS = [
    "Subject1",
    "Subject",
    "subject"
]


def find_project_root():
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

            config_file = current / "config" / "course_code_mapping.json"
            lessondata_dir = current / "lessondata"

            if config_file.exists() and lessondata_dir.exists():
                return current

            if current.parent == current:
                break

            current = current.parent

    raise FileNotFoundError(
        "Project root not found.\n\n"
        "Expected same folder to contain:\n"
        "  config/course_code_mapping.json\n"
        "  lessondata/\n"
    )


PROJECT_ROOT = find_project_root()

LESSON_DATA_DIR = PROJECT_ROOT / "lessondata"
COURSE_MAPPING_FILE = PROJECT_ROOT / "config" / "course_code_mapping.json"
OUTPUT_DIR = PROJECT_ROOT / "output" / "question_lookup"
FAILURE_FILE = OUTPUT_DIR / "lookup_failures.jsonl"
SUMMARY_FILE = OUTPUT_DIR / "question_lookup_summary.json"


def get_folder_subject(subject):
    subject = str(subject).strip().upper()

    if subject.endswith("_EN"):
        return subject.replace("_EN", "")

    return subject


def detect_encoding(file_path):
    with open(file_path, "rb") as f:
        raw = f.read(4)

    if raw.startswith(b"\xff\xfe"):
        return "utf-16"

    if raw.startswith(b"\xfe\xff"):
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
        "latin1"
    ]

    for encoding in encodings:
        try:
            with open(
                file_path,
                "r",
                encoding=encoding,
                errors="strict"
            ) as f:
                f.read(4096)
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
        newline=""
    ) as f:
        sample = f.read(4096)

    if "\t" in sample:
        return "\t"

    try:
        dialect = csv.Sniffer().sniff(
            sample,
            delimiters=["\t", ",", ";", "|"]
        )
        return dialect.delimiter
    except Exception:
        return ","


def normalize_headers(row):
    if not row:
        return {}

    cleaned = {}

    for key, value in row.items():
        if key is None:
            continue

        clean_key = str(key).replace("\ufeff", "").strip()
        cleaned[clean_key] = value

    return cleaned


def get_value(row, possible_columns):
    for column in possible_columns:
        value = row.get(column)

        if value is not None and str(value).strip():
            return str(value).strip()

    return ""


def write_failure(reason, file_name, row_number, row):
    FAILURE_FILE.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    row = normalize_headers(row)

    payload = {
        "reason": reason,
        "file": file_name,
        "row_number": row_number,
        "question_id": get_value(row, QUESTION_ID_COLUMNS),
        "course_code": get_value(row, COURSE_CODE_COLUMNS),
        "subject": get_value(row, SUBJECT_COLUMNS)
    }

    with open(
        FAILURE_FILE,
        "a",
        encoding="utf-8"
    ) as f:
        f.write(
            json.dumps(
                payload,
                ensure_ascii=False
            )
            + "\n"
        )


def load_course_mapping():
    if not COURSE_MAPPING_FILE.exists():
        raise FileNotFoundError(
            f"Course mapping file not found:\n{COURSE_MAPPING_FILE}"
        )

    with open(
        COURSE_MAPPING_FILE,
        "r",
        encoding="utf-8"
    ) as f:
        data = json.load(f)

    normalized = {}

    for course_code, value in data.items():
        subject = str(value["subject"]).strip().upper()
        folder_subject = get_folder_subject(subject)

        normalized[str(course_code).strip()] = {
            "subject": subject,
            "folder_subject": folder_subject,
            "grade": int(value["grade"])
        }

    return normalized


def get_csv_files():
    files = sorted(
        LESSON_DATA_DIR.glob("*.csv")
    )

    if not files:
        raise FileNotFoundError(
            f"No CSV files found in:\n{LESSON_DATA_DIR}"
        )

    return files


def main():
    print("")
    print("=" * 70)
    print("QUESTION LOOKUP BUILDER")
    print("=" * 70)
    print(f"PROJECT_ROOT        : {PROJECT_ROOT}")
    print(f"LESSON_DATA_DIR     : {LESSON_DATA_DIR}")
    print(f"COURSE_MAPPING_FILE : {COURSE_MAPPING_FILE}")
    print(f"OUTPUT_DIR          : {OUTPUT_DIR}")
    print("=" * 70)
    print("")

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    if FAILURE_FILE.exists():
        FAILURE_FILE.unlink()

    course_mapping = load_course_mapping()
    csv_files = get_csv_files()

    subject_lookups = defaultdict(dict)

    stats = defaultdict(
        lambda: {
            "total_rows": 0,
            "unique_questions": 0,
            "duplicates": 0,
            "missing_question_id": 0,
            "missing_course_code": 0,
            "course_code_not_found": 0,
            "grades": set()
        }
    )

    global_seen_question_ids = set()

    print(f"CSV files found: {len(csv_files)}")
    print("")

    for csv_file in csv_files:
        encoding = detect_encoding(csv_file)
        delimiter = detect_delimiter(
            csv_file,
            encoding
        )

        delimiter_name = (
            "TAB"
            if delimiter == "\t"
            else delimiter
        )

        print(
            f"Processing: {csv_file.name} "
            f"| Encoding: {encoding} "
            f"| Delimiter: {delimiter_name}"
        )

        with open(
            csv_file,
            "r",
            encoding=encoding,
            errors="replace",
            newline=""
        ) as f:
            reader = csv.DictReader(
                f,
                delimiter=delimiter
            )

            if not reader.fieldnames:
                write_failure(
                    "missing_headers",
                    csv_file.name,
                    1,
                    {}
                )
                continue

            for row_number, row in enumerate(
                reader,
                start=2
            ):
                row = normalize_headers(row)

                question_id = get_value(
                    row,
                    QUESTION_ID_COLUMNS
                )

                course_code = get_value(
                    row,
                    COURSE_CODE_COLUMNS
                )

                if not course_code:
                    file_subject = csv_file.stem.upper()
                    folder_subject = get_folder_subject(file_subject)

                    stats[folder_subject]["total_rows"] += 1
                    stats[folder_subject]["missing_course_code"] += 1

                    write_failure(
                        "missing_course_code",
                        csv_file.name,
                        row_number,
                        row
                    )

                    continue

                mapping = course_mapping.get(course_code)

                if not mapping:
                    file_subject = csv_file.stem.upper()
                    folder_subject = get_folder_subject(file_subject)

                    stats[folder_subject]["total_rows"] += 1
                    stats[folder_subject]["course_code_not_found"] += 1

                    write_failure(
                        "course_code_not_found",
                        csv_file.name,
                        row_number,
                        row
                    )

                    continue

                subject = mapping["subject"]
                folder_subject = mapping["folder_subject"]
                grade = mapping["grade"]

                stats[folder_subject]["total_rows"] += 1

                if not question_id:
                    stats[folder_subject]["missing_question_id"] += 1

                    write_failure(
                        "missing_question_id",
                        csv_file.name,
                        row_number,
                        row
                    )

                    continue

                if question_id in global_seen_question_ids:
                    stats[folder_subject]["duplicates"] += 1
                    continue

                global_seen_question_ids.add(question_id)

                subject_lookups[folder_subject][question_id] = {
                    "subject": subject,
                    "folder_subject": folder_subject,
                    "grade": grade,
                    "course_code": course_code
                }

                stats[folder_subject]["unique_questions"] += 1
                stats[folder_subject]["grades"].add(grade)

    summary = {
        "generated_at": datetime.now().strftime(
            "%Y-%m-%d %H:%M:%S"
        ),
        "project_root": str(PROJECT_ROOT),
        "lesson_data_dir": str(LESSON_DATA_DIR),
        "course_mapping_file": str(COURSE_MAPPING_FILE),
        "total_unique_questions": len(global_seen_question_ids),
        "subjects": {}
    }

    for folder_subject, lookup in subject_lookups.items():
        subject_dir = OUTPUT_DIR / folder_subject

        subject_dir.mkdir(
            parents=True,
            exist_ok=True
        )

        lookup_file = subject_dir / "question_lookup.json"

        with open(
            lookup_file,
            "w",
            encoding="utf-8"
        ) as f:
            json.dump(
                lookup,
                f,
                indent=2,
                ensure_ascii=False
            )

    for folder_subject, data in stats.items():
        summary["subjects"][folder_subject] = {
            "total_rows": data["total_rows"],
            "unique_questions": data["unique_questions"],
            "duplicates": data["duplicates"],
            "missing_question_id": data["missing_question_id"],
            "missing_course_code": data["missing_course_code"],
            "course_code_not_found": data["course_code_not_found"],
            "grades": sorted(list(data["grades"]))
        }

        subject_dir = OUTPUT_DIR / folder_subject

        subject_dir.mkdir(
            parents=True,
            exist_ok=True
        )

        with open(
            subject_dir / "stats.json",
            "w",
            encoding="utf-8"
        ) as f:
            json.dump(
                summary["subjects"][folder_subject],
                f,
                indent=2,
                ensure_ascii=False
            )

    with open(
        SUMMARY_FILE,
        "w",
        encoding="utf-8"
    ) as f:
        json.dump(
            summary,
            f,
            indent=2,
            ensure_ascii=False
        )

    print("")
    print("=" * 70)
    print("QUESTION LOOKUP BUILD COMPLETE")
    print("=" * 70)

    for folder_subject in sorted(summary["subjects"]):
        data = summary["subjects"][folder_subject]

        print(
            f"{folder_subject:<15}"
            f" Total={data['total_rows']:,}"
            f" Unique={data['unique_questions']:,}"
            f" Duplicates={data['duplicates']:,}"
            f" CourseMissing={data['course_code_not_found']:,}"
            f" MissingQID={data['missing_question_id']:,}"
            f" Grades={data['grades']}"
        )

    print("=" * 70)

    print(
        f"Total Unique Questions : "
        f"{len(global_seen_question_ids):,}"
    )

    print(
        f"Output Folder          : "
        f"{OUTPUT_DIR}"
    )

    print(
        f"Summary File           : "
        f"{SUMMARY_FILE}"
    )

    print(
        f"Failure File           : "
        f"{FAILURE_FILE}"
    )

    print("=" * 70)


if __name__ == "__main__":
    main()