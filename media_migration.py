import os
import json
import time
import signal
from image_resolution_engine.analyzers.dispatcher import analyze_question
from image_transformation.image_processor import process_resolution_output
from image_migration.migration import image_migration, check_json_exists, append_ignored_question

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INPUT_FOLDER = os.path.join(BASE_DIR, "947")
IMAGE_RESOLUTION_OUTPUT = os.path.join(
    BASE_DIR,
    "image_resolution_engine",
    "image_resolution_output"
)

URL = "https://ccl-rc-az.nprd.alefed.com"  # DEV URL
# URL = "https://shared.alefed.com" #PROD URL

stop_requested = False


def handle_sigint(signum, frame):
    global stop_requested
    print("\nCtrl+C detected. Finishing current question, then stopping...")
    stop_requested = True


signal.signal(signal.SIGINT, handle_sigint)


def _atomic_write_json(file_path, data, indent=2):
    """Write via a temp file + os.replace() so a kill mid-write can't corrupt file_path."""
    tmp_path = f"{file_path}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=indent)
    os.replace(tmp_path, file_path)


def write_in_json(file_path, item):
    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    data.append(item)

    _atomic_write_json(file_path, data)


def create_folder(path):
    os.makedirs(path, exist_ok=True)


def create_json(file_path, data=None):
    if data is None:
        data = []

    _atomic_write_json(file_path, data)


def load_processed_ids(file_path):
    """question_processed.json is a flat list of question_ids already fully migrated."""
    if os.path.isfile(file_path):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                return set(data)
        except (json.JSONDecodeError, OSError):
            print(f"[WARNING] Could not read {file_path}; starting with an empty processed set.")
    return set()


def load_ignored_ids(file_path):
    """ignored_question.json is a dict of {question_id: reason}; its keys are also
    excluded from reprocessing so a permanently-missing media file isn't retried every run."""
    if os.path.isfile(file_path):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return set(data.keys())
        except (json.JSONDecodeError, OSError):
            print(f"[WARNING] Could not read {file_path}; starting with an empty ignored set.")
    return set()


# Tracking files (NOT wiped on start - loaded instead, so re-runs can skip already-done work)
question_processed_file = os.path.join(BASE_DIR, "question_processed.json")
ignored_question_file = os.path.join(BASE_DIR, "ignored_question.json")

if not os.path.isfile(question_processed_file):
    create_json(question_processed_file)

processed_ids = load_processed_ids(question_processed_file)
ignored_ids = load_ignored_ids(ignored_question_file)

# Create output folder
create_folder(IMAGE_RESOLUTION_OUTPUT)

start_time = time.perf_counter()

total_questions_processed = 0
total_media_migrated = 0
total_skipped_already_done = 0
total_ignored = 0

for folder in os.listdir(INPUT_FOLDER):
    print(f"Processing Subject - {folder}")

    subject_output = os.path.join(IMAGE_RESOLUTION_OUTPUT, folder)
    create_folder(subject_output)

    input_folder = os.path.join(INPUT_FOLDER, folder)

    for file in os.listdir(input_folder):

        print(f"Processing file - {file}")

        resolution_output_file = os.path.join(subject_output, file)
        create_json(resolution_output_file)

        input_file = os.path.join(input_folder, file)

        with open(input_file, "r", encoding="utf-8") as f:
            questions = json.load(f)

        question_count = 1

        for question in questions:

            if stop_requested:
                print("Stop flag set. Exiting before next question.")
                break

            if not isinstance(question, dict):
                print(f"\t[ERROR] Skipping malformed record at position {question_count} in {file}: "
                      f"expected a JSON object, got {type(question).__name__}")
                question_count += 1
                continue

            question_id = question.get("question_id") or f"UNKNOWN_ID#{folder}#{file}#{question_count}"

            if question_id in processed_ids or question_id in ignored_ids:
                print(f"\t[{question_count}/{len(questions)}] Skipping already processed question :- {question_id}")
                total_skipped_already_done += 1
                question_count += 1
                continue

            try:
                question_type = question["response"]["type"]
                question_code = question["response"]["code"]
            except (KeyError, TypeError) as error:
                reason = f"malformed question record - missing/invalid required field: {error}"
                print(f"\t[ERROR] Skipping {question_id}: {reason}")
                append_ignored_question(question_id, reason)
                ignored_ids.add(question_id)
                total_ignored += 1
                question_count += 1
                continue

            print(f"\t[{question_count}/{len(questions)}] Processing question :- {question_id}")

            # Step 1 - Analyze
            image_resolution = analyze_question(
                question,
                question_type,
                folder
            )

            if image_resolution is None:
                # No image/audio/video anywhere in this question - pass it through untouched.
                print(f"\tNo media found for {question_id} - copying question as-is to final_output")
                final_output_path = os.path.join(BASE_DIR, "final_output", folder)
                check_json_exists(final_output_path, file, question)

                write_in_json(question_processed_file, question_id)
                processed_ids.add(question_id)
                total_questions_processed += 1

                print("\tNext question ...\n")
                question_count += 1
                continue

            write_in_json(resolution_output_file, image_resolution)

            # Step 2 - Transform
            transform_ignore_reason = process_resolution_output(image_resolution)

            if transform_ignore_reason is not None:
                # A media file referenced by this question doesn't exist locally
                # (no download fallback) - abandon the whole question, don't upload.
                print(f"\tIgnored question {question_id}: {transform_ignore_reason}")
                append_ignored_question(question_id, transform_ignore_reason)
                ignored_ids.add(question_id)
                total_ignored += 1

                print("\tNext question ...\n")
                question_count += 1
                continue

            # Step 3 - Upload
            media_count, was_ignored = image_migration(
                URL,
                image_resolution,
                question_code,
                question,
                file,
                folder
            )

            total_media_migrated += media_count

            if was_ignored:
                total_ignored += 1
                ignored_ids.add(question_id)
            else:
                # Track processed question
                write_in_json(question_processed_file, question_id)
                processed_ids.add(question_id)
                total_questions_processed += 1

            print("\tNext question ...\n")

            question_count += 1

        print(f"All questions of {file} are processed ...")

        if stop_requested:
            break

    print(f"{folder} folder processed ...\n")

    if stop_requested:
        break

end_time = time.perf_counter()

print(f"Execution time: {end_time - start_time:.2f} seconds")
print(f"Total questions processed: {total_questions_processed}")
print(f"Total media migrated (image/audio/video): {total_media_migrated}")
print(f"Total questions skipped (already processed): {total_skipped_already_done}")
print(f"Total questions ignored (missing local media): {total_ignored}")
