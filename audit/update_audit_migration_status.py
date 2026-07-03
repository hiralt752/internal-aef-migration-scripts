import argparse
import csv
import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_AUDIT_DIR = PROJECT_ROOT / "audit"
TRANSFORMATION_ENGINE_DIR = PROJECT_ROOT / "transformation_engine"
DEFAULT_REPORT_DIRS = [
    TRANSFORMATION_ENGINE_DIR / "api_report_02_07_2026_PROD",
    TRANSFORMATION_ENGINE_DIR / "api_report_02_07_2026_PROD_02",
    TRANSFORMATION_ENGINE_DIR / "api_report_02_07_2026_PROD_failed",
]
DEFAULT_MAPPING_FILE = PROJECT_ROOT / "migration_id_mapping" / "question_id_mapping.json"
SUCCESS_PREFIXES = ("200_part", "201_part")


def find_audit_csvs(audit_dir: Path) -> list[Path]:
    csv_files = sorted(audit_dir.glob("*.csv"))
    if not csv_files:
        raise FileNotFoundError(f"No CSV files found in {audit_dir}")
    return csv_files


def load_json(path: Path):
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_mapping(mapping_file: Path) -> dict[str, str]:
    data = load_json(mapping_file)
    mapping: dict[str, str] = {}
    for row in data:
        if not isinstance(row, dict):
            continue
        old_id = str(row.get("old_id", "")).strip()
        new_id = row.get("new_id")
        if not old_id:
            continue
        mapping[old_id] = "" if new_id in (None, "") else str(new_id).strip()
    return mapping


def load_success_ids(report_dirs: list[Path]) -> set[str]:
    success_ids: set[str] = set()
    for report_dir in report_dirs:
        for path in sorted(report_dir.glob("*.json")):
            if not any(path.name.startswith(prefix) for prefix in SUCCESS_PREFIXES):
                continue
            data = load_json(path)
            records = data if isinstance(data, list) else [data]
            for row in records:
                if not isinstance(row, dict):
                    continue

                qid = str(row.get("question_id", "")).strip()
                if not qid:
                    continue

                response = row.get("response")
                if isinstance(response, dict) and response.get("id"):
                    success_ids.add(qid)
    return success_ids


def default_report_dirs() -> list[Path]:
    missing = [path for path in DEFAULT_REPORT_DIRS if not path.exists()]
    if missing:
        raise FileNotFoundError(
            "Missing default report directories: " + ", ".join(str(path) for path in missing)
        )
    return DEFAULT_REPORT_DIRS


def update_audit_csv(audit_csv: Path, success_ids: set[str], mapping: dict[str, str]) -> dict[str, int]:
    with audit_csv.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = reader.fieldnames or []
        rows = list(reader)

    required = {"oldQuestionId", "isMigrated", "newQuestionId"}
    missing = required - set(fieldnames)
    if missing:
        raise ValueError(f"Missing required columns in {audit_csv.name}: {sorted(missing)}")

    migrated_yes = 0
    migrated_no = 0
    new_id_filled = 0
    new_id_blank = 0

    for row in rows:
        old_qid = str(row.get("oldQuestionId", "")).strip()
        is_migrated = "Yes" if old_qid in success_ids else "No"
        new_question_id = mapping.get(old_qid, "")

        row["isMigrated"] = is_migrated
        row["newQuestionId"] = new_question_id

        if is_migrated == "Yes":
            migrated_yes += 1
        else:
            migrated_no += 1

        if new_question_id:
            new_id_filled += 1
        else:
            new_id_blank += 1

    backup_path = audit_csv.with_suffix(audit_csv.suffix + ".bak")
    if not backup_path.exists():
        audit_csv.replace(backup_path)
        source_for_write = backup_path
    else:
        source_for_write = audit_csv

    if source_for_write != audit_csv and audit_csv.exists():
        audit_csv.unlink()

    with audit_csv.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    return {
        "rows": len(rows),
        "migrated_yes": migrated_yes,
        "migrated_no": migrated_no,
        "new_id_filled": new_id_filled,
        "new_id_blank": new_id_blank,
        "backup_created": 1 if source_for_write == backup_path else 0,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Update audit CSV isMigrated and newQuestionId from migration artifacts."
    )
    parser.add_argument(
        "--audit-csv",
        type=Path,
        help="Path to one audit CSV. If omitted, all CSV files inside ./audit are updated.",
    )
    parser.add_argument(
        "--report-dir",
        type=Path,
        action="append",
        help="Report directory containing 200_part*.json and 201_part*.json files. Can be passed multiple times. If omitted, only the three configured PROD report folders are used.",
    )
    parser.add_argument(
        "--mapping-file",
        type=Path,
        default=DEFAULT_MAPPING_FILE,
        help="Path to question_id_mapping.json",
    )
    args = parser.parse_args()

    audit_csvs = [args.audit_csv] if args.audit_csv else find_audit_csvs(DEFAULT_AUDIT_DIR)
    report_dirs = args.report_dir or default_report_dirs()
    mapping_file = args.mapping_file

    for audit_csv in audit_csvs:
        if not audit_csv.exists():
            raise FileNotFoundError(f"Audit CSV not found: {audit_csv}")
    for report_dir in report_dirs:
        if not report_dir.exists():
            raise FileNotFoundError(f"Report directory not found: {report_dir}")
    if not mapping_file.exists():
        raise FileNotFoundError(f"Mapping file not found: {mapping_file}")

    mapping = load_mapping(mapping_file)
    success_ids = load_success_ids(report_dirs)

    total_rows = 0
    total_yes = 0
    total_no = 0
    total_new_id_filled = 0
    total_new_id_blank = 0
    total_backups_created = 0

    for audit_csv in audit_csvs:
        stats = update_audit_csv(audit_csv, success_ids, mapping)
        total_rows += stats["rows"]
        total_yes += stats["migrated_yes"]
        total_no += stats["migrated_no"]
        total_new_id_filled += stats["new_id_filled"]
        total_new_id_blank += stats["new_id_blank"]
        total_backups_created += stats["backup_created"]
        print(f"audit_csv={audit_csv}")
        for key, value in stats.items():
            print(f"{key}={value}")

    print(f"audit_csv_count={len(audit_csvs)}")
    print("report_dirs=" + ";".join(str(path) for path in report_dirs))
    print(f"mapping_file={mapping_file}")
    print(f"success_ids={len(success_ids)}")
    print(f"total_rows={total_rows}")
    print(f"total_migrated_yes={total_yes}")
    print(f"total_migrated_no={total_no}")
    print(f"total_new_id_filled={total_new_id_filled}")
    print(f"total_new_id_blank={total_new_id_blank}")
    print(f"total_backups_created={total_backups_created}")


if __name__ == "__main__":
    main()
