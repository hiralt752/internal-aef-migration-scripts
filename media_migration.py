import os
import json
import time
import signal
import datetime
import threading
from concurrent.futures import ThreadPoolExecutor
from dotenv import load_dotenv
from image_resolution_engine.analyzers.dispatcher import analyze_question
from image_transformation.image_processor import process_resolution_output
from image_migration.migration import image_migration, check_json_exists, append_ignored_question


load_dotenv()

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
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            data = []
    except (json.JSONDecodeError, OSError):
        data = []

    updated = False
    if isinstance(item, dict) and "question_id" in item:
        q_id = item["question_id"]
        for idx, val in enumerate(data):
            if isinstance(val, dict) and val.get("question_id") == q_id:
                data[idx] = item
                updated = True
                break

    if not updated:
        data.append(item)

    _atomic_write_json(file_path, data)


def create_folder(path):
    os.makedirs(path, exist_ok=True)


def create_json(file_path, data=None):
    if data is None:
        data = []

    _atomic_write_json(file_path, data)


# ----------------- Chunk Loading and Saving -----------------
_last_saved_chunks = {}


def load_chunks(folder_path, prefix):
    items = []
    if not os.path.isdir(folder_path):
        return items
    idx = 1
    while True:
        file_path = os.path.join(folder_path, f"{prefix}_{idx}.json")
        if os.path.isfile(file_path):
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, list):
                    items.extend(data)
            except (json.JSONDecodeError, OSError) as e:
                print(f"[WARNING] Could not read chunk file {file_path}: {e}")
            idx += 1
        else:
            break
    return items


def save_chunks(folder_path, prefix, items):
    global _last_saved_chunks
    chunk_size = 2000
    os.makedirs(folder_path, exist_ok=True)
    num_chunks = (len(items) + chunk_size - 1) // chunk_size if items else 0

    for i in range(num_chunks):
        chunk_items = items[i * chunk_size : (i + 1) * chunk_size]
        
        # Determine comparison key/value
        if prefix == "success":
            comp_val = chunk_items  # list of strings (ids)
        else:
            comp_val = [q.get("question_id") if isinstance(q, dict) else q for q in chunk_items]

        cache_key = (prefix, i + 1)
        if _last_saved_chunks.get(cache_key) == comp_val:
            continue

        file_path = os.path.join(folder_path, f"{prefix}_{i + 1}.json")
        _atomic_write_json(file_path, chunk_items, indent=4)
        _last_saved_chunks[cache_key] = comp_val

    idx = num_chunks + 1
    while True:
        obsolete_file = os.path.join(folder_path, f"{prefix}_{idx}.json")
        if os.path.exists(obsolete_file):
            try:
                os.remove(obsolete_file)
            except OSError:
                pass
            cache_key = (prefix, idx)
            _last_saved_chunks.pop(cache_key, None)
            idx += 1
        else:
            break


# ----------------- Startup scanning -----------------
def scan_input_folder(input_folder):
    total_questions = 0
    invalid_files_count = 0
    questions_by_file = {}

    if not os.path.exists(input_folder):
        return total_questions, invalid_files_count, questions_by_file

    for folder in sorted(os.listdir(input_folder)):
        folder_path = os.path.join(input_folder, folder)
        if not os.path.isdir(folder_path):
            continue

        for file in sorted(os.listdir(folder_path)):
            if not file.endswith(".json"):
                continue
            file_path = os.path.join(folder_path, file)
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    questions = json.load(f)
                if isinstance(questions, list):
                    questions_by_file[(folder, file)] = questions
                    total_questions += len(questions)
                else:
                    invalid_files_count += 1
            except (json.JSONDecodeError, OSError):
                invalid_files_count += 1

    return total_questions, invalid_files_count, questions_by_file


# Load COUNT_ONLY configuration
count_only_env = os.getenv("COUNT_ONLY", "false").strip().lower()
COUNT_ONLY = count_only_env == "true"

# Report folder setup
report_folder_name = "report_always"
report_folder = os.path.join(BASE_DIR, report_folder_name)

# Create output folder
create_folder(IMAGE_RESOLUTION_OUTPUT)

# Scan files at startup
print("[INFO] Scanning input folder structure...")
total_questions, initial_invalid_json, questions_by_file = scan_input_folder(INPUT_FOLDER)
print(f"[INFO] Scan complete. Found {total_questions} total questions and {initial_invalid_json} invalid JSON files.")

# Load chunks
success_ids_list = load_chunks(report_folder, "success")
success_ids_list = [
    item.get("question_id") if isinstance(item, dict) else item
    for item in success_ids_list
]
success_ids_list = [item for item in success_ids_list if isinstance(item, str)]
success_ids = set(success_ids_list)

failed_questions = load_chunks(report_folder, "failed")
standardized_failed = []
for q in failed_questions:
    if isinstance(q, dict) and "question_id" in q:
        if "error" not in q:
            q_code = q.get("response", {}).get("code") if isinstance(q.get("response"), dict) else q.get("question_code")
            standardized_failed.append({
                "question_id": q["question_id"],
                "subject_code": q.get("subject_code") or "Unknown",
                "question_code": q_code,
                "error": "Legacy failure"
            })
        else:
            standardized_failed.append(q)
failed_questions = standardized_failed
failed_ids = {q["question_id"] for q in failed_questions}

# At startup, sync ignored_question.json entries into the failed report.
# This ensures questions that were ignored in previous runs still appear
# in the failed report even when they haven't been retried yet this session.
IGNORED_QUESTION_FILE = os.path.join(BASE_DIR, "ignored_question.json")
if os.path.isfile(IGNORED_QUESTION_FILE):
    try:
        with open(IGNORED_QUESTION_FILE, "r", encoding="utf-8") as f:
            ignored_data = json.load(f)
        if isinstance(ignored_data, dict):
            for iq_id, iq_reason in ignored_data.items():
                # Skip already-succeeded questions
                if iq_id in success_ids:
                    continue
                # Add to failed report if not already tracked
                if iq_id not in failed_ids:
                    failed_questions.append({
                        "question_id": iq_id,
                        "subject_code": "Unknown",
                        "question_code": None,
                        "error": iq_reason
                    })
                    failed_ids.add(iq_id)
            if failed_questions:
                save_chunks(report_folder, "failed", failed_questions)
                print(f"[INFO] Synced {len(ignored_data)} ignored question(s) into failed report (excluding already-succeeded).")
    except (json.JSONDecodeError, OSError) as e:
        print(f"[WARNING] Could not load ignored_question.json: {e}")

# Initialize progression metrics and thread locks
io_lock = threading.Lock()
skipped_success_count = 0
new_success_count = 0
new_failed_count = 0
new_invalid_json_count = 0

max_workers_env = os.getenv("MAX_WORKERS", "16").strip()
try:
    MAX_WORKERS = int(max_workers_env)
except ValueError:
    MAX_WORKERS = 16

# Pre-calculate skipped success count for startup
for (folder, file), questions in questions_by_file.items():
    for question in questions:
        if isinstance(question, dict):
            q_id = question.get("question_id")
            if q_id and q_id in success_ids:
                skipped_success_count += 1

start_time = time.perf_counter()

if COUNT_ONLY:
    print(f"\n[COUNT ONLY MODE] Enabled")
    print(f"Total questions in folder structure: {total_questions}")
    print(f"Already Succeeded (will be skipped): {skipped_success_count}")
    print(f"Previously Failed (will be retried): {len(failed_ids)}")
    print(f"Remaining / Unprocessed: {total_questions - skipped_success_count}")
    print(f"Invalid JSON files parsed at start: {initial_invalid_json}")
    completed = skipped_success_count + new_success_count + new_failed_count + new_invalid_json_count
    remaining = total_questions - completed
    print(f"[PROGRESS] Completed={completed}/{total_questions} | Remaining={remaining} | Success=0 | Failed=0 | InvalidJSON=0 | Elapsed=00m 00s")
    print("Exiting count only mode.\n")
    os._exit(0)

# Build tasks
tasks = []
for folder, file_list in sorted(questions_by_file.items(), key=lambda x: x[0]):
    subject_folder, filename = folder

    subject_output = os.path.join(IMAGE_RESOLUTION_OUTPUT, subject_folder)
    create_folder(subject_output)

    resolution_output_file = os.path.join(subject_output, filename)
    if not os.path.exists(resolution_output_file):
        create_json(resolution_output_file)

    questions = file_list
    total_in_file = len(questions)
    for q_idx, question in enumerate(questions, 1):
        if not isinstance(question, dict):
            new_invalid_json_count += 1
            continue

        question_id = question.get("question_id") or f"UNKNOWN_ID#{subject_folder}#{filename}#{q_idx}"
        if question_id in success_ids:
            continue

        tasks.append((subject_folder, filename, question_id, question, q_idx, total_in_file, resolution_output_file))

total_media_migrated = 0
total_questions_processed = 0
total_ignored = 0


def process_single_question(task):
    global new_success_count, new_failed_count, new_invalid_json_count
    global total_media_migrated, total_questions_processed, total_ignored
    global success_ids, success_ids_list, failed_ids, failed_questions
    global stop_requested

    if stop_requested:
        return

    subject_folder, filename, question_id, question, q_idx, total_in_file, resolution_output_file = task

    # Parse type and code
    try:
        question_type = question["response"]["type"]
        question_code = question["response"]["code"]
    except (KeyError, TypeError) as error:
        reason = f"malformed question record - missing/invalid required field: {error}"
        with io_lock:
            print(f"\t[ERROR] Skipping {question_id}: {reason}")
            append_ignored_question(question_id, reason)

            # Move from success to failed
            if question_id in success_ids:
                success_ids.remove(question_id)
                success_ids_list = [qid for qid in success_ids_list if qid != question_id]
                save_chunks(report_folder, "success", success_ids_list)

            if question_id not in failed_ids:
                failed_ids.add(question_id)
                failed_questions.append({
                    "question_id": question_id,
                    "subject_code": subject_folder,
                    "question_code": None,
                    "error": reason
                })
                save_chunks(report_folder, "failed", failed_questions)
            else:
                for q in failed_questions:
                    if isinstance(q, dict) and q.get("question_id") == question_id:
                        q["error"] = reason
                        break
                save_chunks(report_folder, "failed", failed_questions)

            new_failed_count += 1
            total_ignored += 1

            # Print progression log
            completed = skipped_success_count + new_success_count + new_failed_count + new_invalid_json_count
            remaining = total_questions - completed
            elapsed_seconds = int(time.perf_counter() - start_time)
            elapsed_str = f"{elapsed_seconds // 60:02d}m {elapsed_seconds % 60:02d}s"
            print(f"[PROGRESS] Completed={completed}/{total_questions} | Remaining={remaining} | Success={new_success_count} | Failed={new_failed_count} | InvalidJSON={new_invalid_json_count} | Elapsed={elapsed_str}")
            print("\tNext question ...\n")
        return

    with io_lock:
        print(f"\t[{q_idx}/{total_in_file}] Processing question :- {question_id}")

    # Step 1 - Analyze
    try:
        image_resolution = analyze_question(
            question,
            question_type,
            subject_folder
        )
    except Exception as e:
        reason = f"exception in analyze_question: {e}"
        with io_lock:
            print(f"\t[ERROR] Failed to analyze {question_id}: {reason}")
            if question_id in success_ids:
                success_ids.remove(question_id)
                success_ids_list = [qid for qid in success_ids_list if qid != question_id]
                save_chunks(report_folder, "success", success_ids_list)
            if question_id not in failed_ids:
                failed_ids.add(question_id)
                failed_questions.append({
                    "question_id": question_id,
                    "subject_code": subject_folder,
                    "question_code": question_code,
                    "error": reason
                })
                save_chunks(report_folder, "failed", failed_questions)
            new_failed_count += 1
            total_ignored += 1
            completed = skipped_success_count + new_success_count + new_failed_count + new_invalid_json_count
            remaining = total_questions - completed
            elapsed_seconds = int(time.perf_counter() - start_time)
            elapsed_str = f"{elapsed_seconds // 60:02d}m {elapsed_seconds % 60:02d}s"
            print(f"[PROGRESS] Completed={completed}/{total_questions} | Remaining={remaining} | Success={new_success_count} | Failed={new_failed_count} | InvalidJSON={new_invalid_json_count} | Elapsed={elapsed_str}")
            print("\tNext question ...\n")
        return

    if image_resolution is None:
        # No image/audio/video anywhere in this question - pass it through untouched.
        with io_lock:
            print(f"\tNo media found for {question_id} - copying question as-is to final_output")
            final_output_path = os.path.join(BASE_DIR, "final_output", subject_folder)
            check_json_exists(final_output_path, filename, question)

            # Move from failed to success
            if question_id in failed_ids:
                failed_ids.remove(question_id)
                failed_questions = [q for q in failed_questions if isinstance(q, dict) and q.get("question_id") != question_id]
                save_chunks(report_folder, "failed", failed_questions)

            if question_id not in success_ids:
                success_ids.add(question_id)
                success_ids_list.append(question_id)
                save_chunks(report_folder, "success", success_ids_list)

            new_success_count += 1
            total_questions_processed += 1

            # Print progression log
            completed = skipped_success_count + new_success_count + new_failed_count + new_invalid_json_count
            remaining = total_questions - completed
            elapsed_seconds = int(time.perf_counter() - start_time)
            elapsed_str = f"{elapsed_seconds // 60:02d}m {elapsed_seconds % 60:02d}s"
            print(f"[PROGRESS] Completed={completed}/{total_questions} | Remaining={remaining} | Success={new_success_count} | Failed={new_failed_count} | InvalidJSON={new_invalid_json_count} | Elapsed={elapsed_str}")
            print("\tNext question ...\n")
        return

    with io_lock:
        write_in_json(resolution_output_file, image_resolution)

    # Step 2 - Transform
    try:
        transform_ignore_reason = process_resolution_output(image_resolution)
    except Exception as e:
        reason = f"exception in process_resolution_output: {e}"
        with io_lock:
            print(f"\t[ERROR] Failed to transform {question_id}: {reason}")
            if question_id in success_ids:
                success_ids.remove(question_id)
                success_ids_list = [qid for qid in success_ids_list if qid != question_id]
                save_chunks(report_folder, "success", success_ids_list)
            if question_id not in failed_ids:
                failed_ids.add(question_id)
                failed_questions.append({
                    "question_id": question_id,
                    "subject_code": subject_folder,
                    "question_code": question_code,
                    "error": reason
                })
                save_chunks(report_folder, "failed", failed_questions)
            new_failed_count += 1
            total_ignored += 1
            completed = skipped_success_count + new_success_count + new_failed_count + new_invalid_json_count
            remaining = total_questions - completed
            elapsed_seconds = int(time.perf_counter() - start_time)
            elapsed_str = f"{elapsed_seconds // 60:02d}m {elapsed_seconds % 60:02d}s"
            print(f"[PROGRESS] Completed={completed}/{total_questions} | Remaining={remaining} | Success={new_success_count} | Failed={new_failed_count} | InvalidJSON={new_invalid_json_count} | Elapsed={elapsed_str}")
            print("\tNext question ...\n")
        return

    if transform_ignore_reason is not None:
        # A media file referenced by this question doesn't exist locally
        with io_lock:
            print(f"\tIgnored question {question_id}: {transform_ignore_reason}")
            append_ignored_question(question_id, transform_ignore_reason)

            # Move from success to failed
            if question_id in success_ids:
                success_ids.remove(question_id)
                success_ids_list = [qid for qid in success_ids_list if qid != question_id]
                save_chunks(report_folder, "success", success_ids_list)

            if question_id not in failed_ids:
                failed_ids.add(question_id)
                failed_questions.append({
                    "question_id": question_id,
                    "subject_code": subject_folder,
                    "question_code": question_code,
                    "error": transform_ignore_reason
                })
                save_chunks(report_folder, "failed", failed_questions)
            else:
                for q in failed_questions:
                    if isinstance(q, dict) and q.get("question_id") == question_id:
                        q["error"] = transform_ignore_reason
                        break
                save_chunks(report_folder, "failed", failed_questions)

            new_failed_count += 1
            total_ignored += 1

            # Print progression log
            completed = skipped_success_count + new_success_count + new_failed_count + new_invalid_json_count
            remaining = total_questions - completed
            elapsed_seconds = int(time.perf_counter() - start_time)
            elapsed_str = f"{elapsed_seconds // 60:02d}m {elapsed_seconds % 60:02d}s"
            print(f"[PROGRESS] Completed={completed}/{total_questions} | Remaining={remaining} | Success={new_success_count} | Failed={new_failed_count} | InvalidJSON={new_invalid_json_count} | Elapsed={elapsed_str}")
            print("\tNext question ...\n")
        return

    # Step 3 - Upload
    try:
        media_count, was_ignored, error_reason = image_migration(
            URL,
            image_resolution,
            question_code,
            question,
            filename,
            subject_folder
        )
    except Exception as e:
        reason = f"exception in image_migration: {e}"
        with io_lock:
            print(f"\t[ERROR] Failed to migrate {question_id}: {reason}")
            if question_id in success_ids:
                success_ids.remove(question_id)
                success_ids_list = [qid for qid in success_ids_list if qid != question_id]
                save_chunks(report_folder, "success", success_ids_list)
            if question_id not in failed_ids:
                failed_ids.add(question_id)
                failed_questions.append({
                    "question_id": question_id,
                    "subject_code": subject_folder,
                    "question_code": question_code,
                    "error": reason
                })
                save_chunks(report_folder, "failed", failed_questions)
            new_failed_count += 1
            total_ignored += 1
            completed = skipped_success_count + new_success_count + new_failed_count + new_invalid_json_count
            remaining = total_questions - completed
            elapsed_seconds = int(time.perf_counter() - start_time)
            elapsed_str = f"{elapsed_seconds // 60:02d}m {elapsed_seconds % 60:02d}s"
            print(f"[PROGRESS] Completed={completed}/{total_questions} | Remaining={remaining} | Success={new_success_count} | Failed={new_failed_count} | InvalidJSON={new_invalid_json_count} | Elapsed={elapsed_str}")
            print("\tNext question ...\n")
        return

    with io_lock:
        total_media_migrated += media_count

        # Determine total media that should have been migrated
        key_list = ["question_images", "option_images", "image_audit", "question_audios", "question_videos"]
        total_media_in_question = 0
        for key in key_list:
            if image_resolution.get(key):
                total_media_in_question += len(image_resolution[key])

        is_success = False
        if not was_ignored and media_count == total_media_in_question:
            is_success = True

        if is_success:
            # Move from failed to success
            if question_id in failed_ids:
                failed_ids.remove(question_id)
                failed_questions = [q for q in failed_questions if isinstance(q, dict) and q.get("question_id") != question_id]
                save_chunks(report_folder, "failed", failed_questions)

            if question_id not in success_ids:
                success_ids.add(question_id)
                success_ids_list.append(question_id)
                save_chunks(report_folder, "success", success_ids_list)

            new_success_count += 1
            total_questions_processed += 1
        else:
            err_msg = error_reason or "Unknown upload failure"
            # Move from success to failed
            if question_id in success_ids:
                success_ids.remove(question_id)
                success_ids_list = [qid for qid in success_ids_list if qid != question_id]
                save_chunks(report_folder, "success", success_ids_list)

            if question_id not in failed_ids:
                failed_ids.add(question_id)
                failed_questions.append({
                    "question_id": question_id,
                    "subject_code": subject_folder,
                    "question_code": question_code,
                    "error": err_msg
                })
                save_chunks(report_folder, "failed", failed_questions)
            else:
                for q in failed_questions:
                    if isinstance(q, dict) and q.get("question_id") == question_id:
                        q["error"] = err_msg
                        break
                save_chunks(report_folder, "failed", failed_questions)

            new_failed_count += 1
            total_ignored += 1

        # Print progression log
        completed = skipped_success_count + new_success_count + new_failed_count + new_invalid_json_count
        remaining = total_questions - completed
        elapsed_seconds = int(time.perf_counter() - start_time)
        elapsed_str = f"{elapsed_seconds // 60:02d}m {elapsed_seconds % 60:02d}s"
        print(f"[PROGRESS] Completed={completed}/{total_questions} | Remaining={remaining} | Success={new_success_count} | Failed={new_failed_count} | InvalidJSON={new_invalid_json_count} | Elapsed={elapsed_str}")
        print("\tNext question ...\n")


# Print initial progression log
initial_completed = skipped_success_count + new_success_count + new_failed_count + new_invalid_json_count
initial_remaining = total_questions - initial_completed
print(f"[PROGRESS] Completed={initial_completed}/{total_questions} | Remaining={initial_remaining} | Success=0 | Failed=0 | InvalidJSON=0 | Elapsed=00m 00s")
print("\tNext question ...\n")

print(f"[INFO] Starting multithreaded processing with {MAX_WORKERS} workers...")
with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
    executor.map(process_single_question, tasks)

end_time = time.perf_counter()

print(f"Execution time: {end_time - start_time:.2f} seconds")
print(f"Total questions processed: {total_questions_processed}")
print(f"Total media migrated (image/audio/video): {total_media_migrated}")
print(f"Total questions skipped (already processed): {skipped_success_count}")
print(f"Total questions ignored/failed: {total_ignored}")

