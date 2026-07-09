import argparse
import json
import os
from collections import Counter
from datetime import datetime
from pathlib import Path


INPUT_DIR_NAME = "input"
UPDATE_LANGUAGES = False
UPDATE_ENV_VAR = "AI_ENGINE_UPDATE_INPUT_LANGUAGES"

LANGUAGE_MAPPING = {
    "AR": "Arabic",
    "EN_CA": "English US",
    "EN_GB": "English GB",
    "EN_US": "English US",
    "FRA_FR": "French FR",
    "IND": "Indonesian",
    "SPA": "Spanish",
    "UZB": "Uzbek",
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

            if (current / INPUT_DIR_NAME).exists():
                return current

            if current.parent == current:
                break

            current = current.parent

    raise FileNotFoundError("Project root not found. Expected input/.")


PROJECT_ROOT = resolve_project_root()
DOTENV_FILE = PROJECT_ROOT / ".env"


def load_json_file(file_path):
    with open(file_path, "r", encoding="utf-8-sig") as handle:
        return json.load(handle)


def write_json_file(file_path, data):
    file_path.parent.mkdir(parents=True, exist_ok=True)

    with open(file_path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


def parse_bool(value, default=False):
    if value is None:
        return default

    normalized = str(value).strip().lower()

    if normalized in {"1", "true", "yes", "y", "on"}:
        return True

    if normalized in {"0", "false", "no", "n", "off"}:
        return False

    return default


def load_dotenv_value(file_path, key):
    if not file_path.exists():
        return None

    try:
        lines = file_path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return None

    for raw_line in lines:
        line = raw_line.strip()

        if not line or line.startswith("#") or "=" not in line:
            continue

        current_key, current_value = line.split("=", 1)

        if current_key.strip() != key:
            continue

        value = current_value.strip()

        if (
            len(value) >= 2
            and value[0] == value[-1]
            and value[0] in {"'", '"'}
        ):
            value = value[1:-1]

        return value

    return None


def get_language(record):
    return (
        (record.get("metadata") or {})
        .get("general", {})
        .get("language")
    )


def set_language(record, value):
    metadata = record.setdefault("metadata", {})
    general = metadata.setdefault("general", {})
    general["language"] = value


def iter_input_json_files(input_root):
    return sorted(input_root.rglob("*.json"))


def analyze_languages(input_root):
    language_counts = Counter()
    unknown_counts = Counter()
    file_count = 0
    record_count = 0
    missing_language_count = 0
    files_with_changes = 0
    records_mappable = 0

    for json_file in iter_input_json_files(input_root):
        file_count += 1
        file_has_mappable_record = False

        try:
            payload = load_json_file(json_file)
        except Exception:
            continue

        if not isinstance(payload, list):
            continue

        for record in payload:
            if not isinstance(record, dict):
                continue

            record_count += 1
            language = get_language(record)
            normalized = str(language).strip() if language is not None else ""

            if not normalized:
                missing_language_count += 1
                language_counts[""] += 1
                continue

            language_counts[normalized] += 1

            if normalized in LANGUAGE_MAPPING:
                records_mappable += 1
                file_has_mappable_record = True
            elif normalized not in LANGUAGE_MAPPING.values():
                unknown_counts[normalized] += 1

        if file_has_mappable_record:
            files_with_changes += 1

    mapped_preview = {
        source: LANGUAGE_MAPPING[source]
        for source in sorted(language_counts.keys())
        if source in LANGUAGE_MAPPING
    }

    return {
        "generated_at": datetime.now().isoformat(),
        "input_root": str(input_root),
        "file_count": file_count,
        "record_count": record_count,
        "files_with_mappable_records": files_with_changes,
        "records_mappable": records_mappable,
        "missing_language_count": missing_language_count,
        "language_counts": dict(sorted(language_counts.items())),
        "mapped_preview": mapped_preview,
        "unknown_languages": dict(sorted(unknown_counts.items())),
    }


def update_languages(input_root):
    updated_files = 0
    updated_records = 0
    unchanged_records = 0
    unknown_counts = Counter()

    for json_file in iter_input_json_files(input_root):
        try:
            payload = load_json_file(json_file)
        except Exception:
            continue

        if not isinstance(payload, list):
            continue

        file_changed = False

        for record in payload:
            if not isinstance(record, dict):
                continue

            language = get_language(record)
            normalized = str(language).strip() if language is not None else ""

            if not normalized:
                unchanged_records += 1
                continue

            if normalized in LANGUAGE_MAPPING:
                target = LANGUAGE_MAPPING[normalized]

                if normalized != target:
                    set_language(record, target)
                    updated_records += 1
                    file_changed = True
                else:
                    unchanged_records += 1
            elif normalized in LANGUAGE_MAPPING.values():
                unchanged_records += 1
            else:
                unknown_counts[normalized] += 1
                unchanged_records += 1

        if file_changed:
            with open(json_file, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2, ensure_ascii=False)
                handle.write("\n")
            updated_files += 1

    return {
        "generated_at": datetime.now().isoformat(),
        "input_root": str(input_root),
        "updated_files": updated_files,
        "updated_records": updated_records,
        "unchanged_records": unchanged_records,
        "unknown_languages": dict(sorted(unknown_counts.items())),
    }


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Report distinct metadata.general.language values in input JSON files "
            "and optionally update them using a fixed mapping."
        )
    )
    parser.add_argument(
        "--project-root",
        default=str(PROJECT_ROOT),
        help="Project root containing input/.",
    )
    parser.add_argument(
        "--report-json",
        default="",
        help="Optional path to write the report/update summary as JSON.",
    )
    args = parser.parse_args()

    project_root = Path(args.project_root).resolve()
    input_root = project_root / INPUT_DIR_NAME

    env_value = os.getenv(UPDATE_ENV_VAR)

    if env_value is None:
        env_value = load_dotenv_value(project_root / ".env", UPDATE_ENV_VAR)

    should_update = parse_bool(
        env_value,
        default=UPDATE_LANGUAGES,
    )

    if should_update:
        result = update_languages(input_root)
        print("Mode: update")
        print(
            f"Update control: script flag={UPDATE_LANGUAGES}, "
            f"env {UPDATE_ENV_VAR}={env_value!r}"
        )
        print(f"Updated files: {result['updated_files']}")
        print(f"Updated records: {result['updated_records']}")
        print(f"Unknown languages: {len(result['unknown_languages'])}")
    else:
        result = analyze_languages(input_root)
        print("Mode: report")
        print(
            f"Update control: script flag={UPDATE_LANGUAGES}, "
            f"env {UPDATE_ENV_VAR}={env_value!r}"
        )
        print(f"Files scanned: {result['file_count']}")
        print(f"Records scanned: {result['record_count']}")
        print("Distinct language values:")

        for language, count in result["language_counts"].items():
            display = language if language else "<blank>"
            mapped_to = result["mapped_preview"].get(language, "")

            if mapped_to:
                print(f"  {display}: {count} -> {mapped_to}")
            else:
                print(f"  {display}: {count}")

        if result["unknown_languages"]:
            print("Languages outside mapping:")
            for language, count in result["unknown_languages"].items():
                print(f"  {language}: {count}")
        else:
            print("Languages outside mapping: none")

    if args.report_json:
        report_path = Path(args.report_json)

        if not report_path.is_absolute():
            report_path = project_root / report_path

        write_json_file(report_path, result)
        print(f"Report JSON written: {report_path}")


if __name__ == "__main__":
    main()
