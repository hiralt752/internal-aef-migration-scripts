import json
from pathlib import Path
from collections import defaultdict
from datetime import datetime

from services.question_reader import (
    read_json_file,
    iter_question_files
)
from services.html_text_extractor import (
    extract_text_from_content,
    collect_feedback_texts,
    collect_hint_texts,
    remove_duplicates
)
from services.correct_answer_extractor import (
    extract_correct_answers,
    build_option_text_map
)
from services.image_extractor import (
    load_image_mapping,
    extract_images_from_question
)
from services.prompt_builder import build_prompt
from services.progress_logger import ProgressLogger
from services.json_utils import write_json_file


INPUT_DIR_NAME = "input"
QUESTION_LOOKUP_DIR_NAME = "output/question_lookup"
OUTPUT_DIR_NAME = "output/prompt_preview"


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

            if (
                (current / QUESTION_LOOKUP_DIR_NAME).exists()
                and
                (current / INPUT_DIR_NAME).exists()
            ):
                return current

            if current.parent == current:
                break

            current = current.parent

    raise FileNotFoundError(
        "Project root not found. Expected:\n"
        f"  {INPUT_DIR_NAME}/\n"
        f"  {QUESTION_LOOKUP_DIR_NAME}/\n"
    )


PROJECT_ROOT = find_project_root()
INPUT_DIR = PROJECT_ROOT / INPUT_DIR_NAME
QUESTION_LOOKUP_DIR = PROJECT_ROOT / QUESTION_LOOKUP_DIR_NAME
OUTPUT_DIR = PROJECT_ROOT / OUTPUT_DIR_NAME


def iter_input_roots():
    if not INPUT_DIR.exists():
        return []

    return sorted(
        path
        for path in INPUT_DIR.iterdir()
        if path.is_dir()
    )


def get_input_root_for_file(file_path):
    file_path = Path(file_path).resolve()

    for input_root in iter_input_roots():
        try:
            file_path.relative_to(
                input_root.resolve()
            )
            return input_root
        except ValueError:
            continue

    return None


def clear_existing_prompt_preview_output():
    if not OUTPUT_DIR.exists():
        return

    for file_path in OUTPUT_DIR.rglob(
        "*.json"
    ):
        if file_path.name in {
            "failed_prompt_preview.json",
            "summary.json"
        }:
            continue

        file_path.unlink()

    for file_name in [
        "failed_prompt_preview.json",
        "summary.json"
    ]:
        target = OUTPUT_DIR / file_name

        if target.exists():
            target.unlink()


def group_records_by_question_type(records):
    grouped = defaultdict(list)

    for record in records or []:
        question_type = str(
            record.get("question_type")
            or "UNKNOWN"
        ).strip() or "UNKNOWN"
        grouped[question_type].append(record)

    return dict(
        sorted(grouped.items())
    )


def load_question_lookup_index():
    index = {}

    lookup_files = sorted(
        QUESTION_LOOKUP_DIR.rglob(
            "question_lookup.json"
        )
    )

    for lookup_file in lookup_files:
        with open(
            lookup_file,
            "r",
            encoding="utf-8"
        ) as f:
            data = json.load(f)

        for question_id, meta in data.items():
            index[question_id] = meta

    return index


def get_external_id(question):
    return (
        question
        .get("metadata", {})
        .get("general", {})
        .get("externalId")
        
    )


def get_statement_texts(question):
    item_body = question.get(
        "itemBody",
        {}
    )

    texts = []

    statement = item_body.get(
        "statement"
    )

    if isinstance(statement, dict):
        content = statement.get(
            "content"
        )

        texts.extend(
            extract_text_from_content(content)
        )

    sentence = item_body.get(
        "sentence"
    )

    if isinstance(sentence, dict):
        text = sentence.get("text")

        texts.extend(
            extract_text_from_content(text)
        )

    return remove_duplicates(texts)


def get_options(question):
    item_body = question.get(
        "itemBody",
        {}
    )

    question_type = str(
        question.get("type", "")
    ).strip().upper()

    options = []

    if question_type in [
        "DROPDOWN",
        "SELECT_A_BLANK"
    ]:
        items = item_body.get(
            "items",
            []
        )

        for item in items:
            dropdown_id = item.get("id")

            for option in item.get("options", []):
                option_id = option.get("id")
                content = option.get(
                    "content",
                    {}
                )

                text = ""

                if isinstance(content, dict):
                    text_values = extract_text_from_content(
                        content.get("text")
                    )

                    text = (
                        text_values[0]
                        if text_values
                        else ""
                    )

                options.append(
                    {
                        "id": option_id,
                        "dropdown_id": dropdown_id,
                        "text": text,
                        "images": []
                    }
                )

        return options

    option_map = build_option_text_map(
        question
    )

    for option_id, text in option_map.items():
        options.append(
            {
                "id": option_id,
                "text": text,
                "images": []
            }
        )

    return options


def get_word_bank(question):
    item_body = question.get(
        "itemBody",
        {}
    )

    word_bank = []

    distractors = item_body.get(
        "wordBankDistractor",
        []
    )

    if isinstance(distractors, list):
        for item in distractors:
            if isinstance(item, str):
                word_bank.append(item)

    options = item_body.get(
        "options",
        []
    )

    if isinstance(options, list):
        for option in options:
            if not isinstance(option, dict):
                continue

            content = option.get("content")

            if isinstance(content, dict):
                text_values = extract_text_from_content(
                    content.get("text")
                )

                word_bank.extend(text_values)

            elif isinstance(content, str):
                word_bank.extend(
                    extract_text_from_content(content)
                )

    return remove_duplicates(word_bank)


def get_targets(question):
    item_body = question.get(
        "itemBody",
        {}
    )

    targets = item_body.get(
        "targets",
        []
    )

    if isinstance(targets, list):
        return targets

    return []


def build_normalized_question(
    question,
    lookup_index,
    image_mapping
):
    question_id = get_external_id(
        question
    )

    if not question_id:
        return None

    lookup_meta = lookup_index.get(
        question_id,
        {}
    )

    subject = lookup_meta.get(
        "subject",
        ""
    )

    folder_subject = lookup_meta.get(
        "folder_subject",
        ""
    )

    grade = lookup_meta.get(
        "grade",
        ""
    )

    course_code = lookup_meta.get(
        "course_code",
        ""
    )

    statements = get_statement_texts(
        question
    )

    images = extract_images_from_question(
        question=question,
        image_mapping=image_mapping,
        project_root=PROJECT_ROOT,
        subject=folder_subject or subject
    )

    normalized = {
        "question_id": question_id,
        "question_type": str(
            question.get("type", "")
        ).strip().upper(),
        "question_sub_type": str(
            question.get("subType", "")
        ).strip().upper(),
        "subject": subject,
        "folder_subject": folder_subject,
        "grade": grade,
        "course_code": course_code,
        "question_body": statements,
        "statements": statements,
        "options": get_options(question),
        "word_bank": get_word_bank(question),
        "targets": get_targets(question),
        "correct_answers": extract_correct_answers(
            question
        ),
        "images": images,
        "hints": collect_hint_texts(question),
        "feedback": collect_feedback_texts(question)
    }

    return normalized


def summarize_prompt_preview_output(
    output_by_input
):
    by_input = {}
    by_question_type = defaultdict(int)
    image_statuses = defaultdict(int)

    for input_name, subject_records in output_by_input.items():
        input_summary = {
            "subjects": {},
            "prompts": 0,
            "image_questions": 0,
            "total_images": 0,
            "resolved_images": 0,
            "unresolved_images": 0,
            "question_types": defaultdict(int),
            "image_statuses": defaultdict(int)
        }

        for subject, records in subject_records.items():
            subject_summary = {
                "prompts": len(records),
                "image_questions": 0,
                "total_images": 0,
                "resolved_images": 0,
                "unresolved_images": 0,
                "question_types": defaultdict(int),
                "image_statuses": defaultdict(int)
            }

            for record in records:
                question_type = str(
                    record.get("question_type")
                    or "UNKNOWN"
                )

                subject_summary["question_types"][question_type] += 1
                input_summary["question_types"][question_type] += 1
                by_question_type[question_type] += 1

                images = (
                    record
                    .get("normalized_input", {})
                    .get("images", [])
                    or []
                )

                if images:
                    subject_summary["image_questions"] += 1
                    input_summary["image_questions"] += 1

                subject_summary["total_images"] += len(images)
                input_summary["total_images"] += len(images)

                for image in images:
                    status = str(
                        image.get("status")
                        or "unknown"
                    )

                    subject_summary["image_statuses"][status] += 1
                    input_summary["image_statuses"][status] += 1
                    image_statuses[status] += 1

                    if image.get("exists") is True:
                        subject_summary["resolved_images"] += 1
                        input_summary["resolved_images"] += 1
                    else:
                        subject_summary["unresolved_images"] += 1
                        input_summary["unresolved_images"] += 1

            subject_summary["question_types"] = dict(
                sorted(subject_summary["question_types"].items())
            )
            subject_summary["image_statuses"] = dict(
                sorted(subject_summary["image_statuses"].items())
            )

            input_summary["subjects"][subject] = subject_summary
            input_summary["prompts"] += len(records)

        input_summary["subjects"] = dict(
            sorted(input_summary["subjects"].items())
        )
        input_summary["question_types"] = dict(
            sorted(input_summary["question_types"].items())
        )
        input_summary["image_statuses"] = dict(
            sorted(input_summary["image_statuses"].items())
        )

        by_input[input_name] = input_summary

    return {
        "by_input": dict(
            sorted(by_input.items())
        ),
        "by_question_type": dict(
            sorted(
                by_question_type.items()
            )
        ),
        "image_statuses": dict(
            sorted(
                image_statuses.items()
            )
        )
    }


def build_image_alignment_report(
    output_by_input
):
    report = {
        "by_input": {},
        "mismatch_inputs": []
    }

    for input_name, subject_records in sorted(output_by_input.items()):
        input_total = 0
        input_with_images = 0
        subject_details = {}
        file_details = defaultdict(
            lambda: {
                "total_records": 0,
                "with_images": 0
            }
        )

        for subject, records in sorted(subject_records.items()):
            subject_total = len(records)
            subject_with_images = 0

            for record in records:
                input_total += 1

                if record.get("has_images"):
                    input_with_images += 1
                    subject_with_images += 1

                source_file = str(
                    record.get("source_file")
                    or "unknown_source"
                )
                file_details[source_file]["total_records"] += 1

                if record.get("has_images"):
                    file_details[source_file]["with_images"] += 1

            subject_details[subject] = {
                "total_records": subject_total,
                "with_images": subject_with_images,
                "without_images": subject_total - subject_with_images
            }

        file_report = []

        for source_file, stats in sorted(file_details.items()):
            without_images = (
                stats["total_records"]
                - stats["with_images"]
            )

            if without_images <= 0:
                continue

            file_report.append(
                {
                    "source_file": source_file,
                    "total_records": stats["total_records"],
                    "with_images": stats["with_images"],
                    "without_images": without_images
                }
            )

        input_report = {
            "total_records": input_total,
            "with_images": input_with_images,
            "without_images": input_total - input_with_images,
            "subjects": subject_details,
            "files_with_missing_images": file_report[:50]
        }

        report["by_input"][input_name] = input_report

        if "with_images" in input_name.lower():
            if input_with_images != input_total:
                report["mismatch_inputs"].append(
                    {
                        "input_name": input_name,
                        "expected_all_with_images": True,
                        "total_records": input_total,
                        "with_images": input_with_images,
                        "without_images": input_total - input_with_images
                    }
                )

    return report


def main():
    print("")
    print("=" * 70)
    print("PROMPT PREVIEW BUILDER")
    print("=" * 70)
    print(f"PROJECT_ROOT        : {PROJECT_ROOT}")
    print(f"INPUT_DIR           : {INPUT_DIR}")
    print(f"QUESTION_LOOKUP_DIR : {QUESTION_LOOKUP_DIR}")
    print(f"OUTPUT_DIR          : {OUTPUT_DIR}")
    print("=" * 70)
    print("")

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True
    )
    clear_existing_prompt_preview_output()

    lookup_index = load_question_lookup_index()
    image_mapping = load_image_mapping(
        PROJECT_ROOT
    )

    input_roots = iter_input_roots()
    question_files = []

    for input_root in input_roots:
        question_files.extend(
            iter_question_files(
                input_root
            )
        )

    print(f"[INFO] Total JSON files found: {len(question_files):,}")
    print(f"[INFO] Input folders found   : {len(input_roots):,}")
    print("[INFO] Loading and processing questions...")
    print("")

    output_by_input = defaultdict(
        lambda: defaultdict(list)
    )
    failed = []

    processed_count = 0
    success_count = 0
    failed_count = 0
    image_question_count = 0
    total_image_count = 0

    progress = ProgressLogger(
        total=None,
        log_every=100,
        log_seconds=30
    )

    for file_path in question_files:
        try:
            questions = read_json_file(
                file_path
            )

        except Exception as e:
            failed.append(
                {
                    "file": str(file_path),
                    "reason": f"file_read_error: {e}"
                }
            )
            failed_count += 1
            continue

        print(
            f"[FILE_START] {file_path} | "
            f"Records={len(questions):,}",
            flush=True
        )

        for question in questions:
            processed_count += 1

            try:
                normalized = build_normalized_question(
                    question,
                    lookup_index,
                    image_mapping
                )

                if not normalized:
                    failed.append(
                        {
                            "file": str(file_path),
                            "reason": "missing_external_id"
                        }
                    )
                    failed_count += 1
                    continue

                images = normalized.get(
                    "images",
                    []
                )

                if images:
                    image_question_count += 1
                    total_image_count += len(images)

                prompt = build_prompt(
                    normalized
                )

                record = {
                    "question_id": normalized["question_id"],
                    "question_type": normalized["question_type"],
                    "question_sub_type": normalized["question_sub_type"],
                    "subject": normalized["subject"],
                    "folder_subject": normalized["folder_subject"],
                    "grade": normalized["grade"],
                    "course_code": normalized["course_code"],
                    "image_count": len(images),
                    "has_images": bool(images),
                    "input_root": None,
                    "source_file": None,
                    "normalized_input": normalized,
                    "prompt": prompt
                }

                folder_subject = (
                    normalized.get("folder_subject")
                    or normalized.get("subject")
                    or "UNKNOWN"
                )
                input_root = get_input_root_for_file(
                    file_path
                )
                input_root_name = (
                    input_root.name
                    if input_root
                    else "unknown_input"
                )
                record["input_root"] = input_root_name
                record["source_file"] = str(
                    file_path.relative_to(PROJECT_ROOT)
                )

                output_by_input[input_root_name][folder_subject].append(record)

                success_count += 1

            except Exception as e:
                failed.append(
                    {
                        "file": str(file_path),
                        "reason": str(e)
                    }
                )
                failed_count += 1

            progress.log(
                processed=processed_count,
                success=success_count,
                failed=failed_count,
                image_questions=image_question_count,
                total_images=total_image_count,
                current_file=file_path
            )

        print(
            f"[FILE_DONE] {file_path} | "
            f"Processed So Far={processed_count:,} | "
            f"Success={success_count:,} | "
            f"Failed={failed_count:,}",
            flush=True
        )
        print("")

    print("[INFO] Writing prompt preview files...")

    for input_name, subject_records in output_by_input.items():
        for subject, records in subject_records.items():
            subject_dir = OUTPUT_DIR / input_name / subject

            subject_dir.mkdir(
                parents=True,
                exist_ok=True
            )

            for question_type, question_type_records in group_records_by_question_type(records).items():
                question_type_file = (
                    subject_dir
                    / f"{question_type}.json"
                )

                write_json_file(
                    question_type_file,
                    question_type_records
                )

    failed_file = OUTPUT_DIR / "failed_prompt_preview.json"

    write_json_file(
        failed_file,
        failed
    )

    output_breakdown = summarize_prompt_preview_output(output_by_input)
    image_alignment_report = build_image_alignment_report(
        output_by_input
    )

    summary = {
        "generated_at": datetime.now().strftime(
            "%Y-%m-%d %H:%M:%S"
        ),
        "total_input_folders": len(output_by_input),
        "total_subjects": sum(
            len(subject_records)
            for subject_records in output_by_input.values()
        ),
        "total_processed": processed_count,
        "total_prompts": success_count,
        "failed": failed_count,
        "image_questions": image_question_count,
        "total_images": total_image_count,
        "breakdown": output_breakdown,
        "image_alignment_report": image_alignment_report
    }

    summary_file = OUTPUT_DIR / "summary.json"

    write_json_file(
        summary_file,
        summary
    )

    write_json_file(
        OUTPUT_DIR / "image_alignment_report.json",
        image_alignment_report
    )

    print("")
    print("=" * 70)
    print("PROMPT PREVIEW COMPLETE")
    print("=" * 70)

    for input_name in sorted(output_by_input):
        total_records = sum(
            len(records)
            for records in output_by_input[input_name].values()
        )
        print(f"{input_name:<35} Prompts={total_records:,}")

    print("=" * 70)
    print(f"Total Processed : {processed_count:,}")
    print(f"Total Prompts   : {success_count:,}")
    print(f"Failed          : {failed_count:,}")
    print(f"Image Questions : {image_question_count:,}")
    print(f"Total Images    : {total_image_count:,}")
    for mismatch in image_alignment_report.get(
        "mismatch_inputs",
        []
    ):
        print(
            "[WARN] Input folder marked with images has text-only records: "
            f"{mismatch['input_name']} | "
            f"WithImages={mismatch['with_images']:,} | "
            f"WithoutImages={mismatch['without_images']:,}"
        )
    print(
        "Image Statuses  : "
        f"{output_breakdown.get('image_statuses', {})}"
    )
    print(f"Output Dir      : {OUTPUT_DIR}")
    print("=" * 70)


if __name__ == "__main__":
    main()
