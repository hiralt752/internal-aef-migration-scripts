"""
Image migration script.

Fetches questions sequentially from core_seperated_data_input and passes each
one to image_resolution_engine for processing.
"""

import json
import os
import signal
import sys
from typing import Any

# =============================================================================
# CONFIGURATION
# =============================================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INPUT_ROOT = os.path.join(BASE_DIR, "core_seperated_data_input")
ENGINE_DIR = os.path.join(BASE_DIR, "image_resolution_engine")
TRANSFORMATION_DIR = os.path.join(BASE_DIR, "image_transformation")
RESOLUTION_OUTPUT_ROOT = os.path.join(ENGINE_DIR, "image_resolution_output")
TRANSFORMATION_OUTPUT_ROOT = os.path.join(
    TRANSFORMATION_DIR, "image_transformation_output"
)
PROGRESS_FILE = os.path.join(RESOLUTION_OUTPUT_ROOT, "progress.json")

# Allow imports from image_resolution_engine (analyzers, helpers, etc.)
sys.path.insert(0, ENGINE_DIR)
sys.path.insert(0, BASE_DIR)

from analyzers.dispatcher import analyze_question
from helpers.resolution_debugger import log_skip, log_success
from image_transformation.image_processor import process_resolution_output

# =============================================================================
# GLOBAL STATE
# =============================================================================

shutdown_requested = False


# =============================================================================
# UTILITY FUNCTIONS - LOGGING
# =============================================================================

def log_info(message: str) -> None:
    print(f"[INFO] {message}")


def log_warning(message: str) -> None:
    print(f"[WARNING] {message}")


def log_error(message: str) -> None:
    print(f"[ERROR] {message}")


# =============================================================================
# UTILITY FUNCTIONS - FILE / JSON
# =============================================================================

def load_json_file(file_path: str) -> list[dict[str, Any]] | None:
    """Load and validate a JSON file. Returns None on failure."""
    if not os.path.isfile(file_path):
        log_error(f"File not found: {file_path}")
        return None

    try:
        with open(file_path, "r", encoding="utf-8") as file:
            data = json.load(file)
    except json.JSONDecodeError as error:
        log_error(f"Invalid JSON in {file_path}: {error}")
        return None
    except OSError as error:
        log_error(f"Failed to read {file_path}: {error}")
        return None

    if not isinstance(data, list):
        log_error(f"Expected a JSON array in {file_path}")
        return None

    return data


def load_progress() -> dict[str, Any]:
    """Load saved progress from disk."""
    if not os.path.isfile(PROGRESS_FILE):
        return {"processed_question_ids": []}

    try:
        with open(PROGRESS_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)
        if not isinstance(data, dict):
            return {"processed_question_ids": []}
        data.setdefault("processed_question_ids", [])
        return data
    except (json.JSONDecodeError, OSError) as error:
        log_warning(f"Could not load progress file, starting fresh: {error}")
        return {"processed_question_ids": []}


def save_progress(progress: dict[str, Any]) -> None:
    """Persist progress to disk."""
    ensure_directory(RESOLUTION_OUTPUT_ROOT)
    with open(PROGRESS_FILE, "w", encoding="utf-8") as file:
        json.dump(progress, file, ensure_ascii=False, indent=2)
    log_info("Progress saved.")


def ensure_directory(directory_path: str) -> None:
    """Create a directory if it does not already exist."""
    if not directory_path:
        return

    normalized_path = os.path.normpath(os.path.abspath(directory_path))

    if not os.path.isdir(normalized_path):
        os.makedirs(normalized_path, exist_ok=True)
        log_info(f"Folder created: {normalized_path}")


def append_resolution_output(result: dict[str, Any]) -> None:
    """Append one engine result to image_resolution_output (same format as main.py)."""
    source_type = result.get("source_type", "unknown")
    output_file = os.path.join(RESOLUTION_OUTPUT_ROOT, f"{source_type}.json")

    existing_results: list[dict[str, Any]] = []
    if os.path.isfile(output_file):
        try:
            with open(output_file, "r", encoding="utf-8") as file:
                data = json.load(file)
            if isinstance(data, list):
                existing_results = data
        except (json.JSONDecodeError, OSError) as error:
            log_warning(f"Could not read existing output file, starting fresh: {error}")

    existing_results.append(result)

    with open(output_file, "w", encoding="utf-8") as file:
        json.dump(existing_results, file, ensure_ascii=False, indent=2)

    log_info(f"File updated: {output_file}")


# =============================================================================
# GRACEFUL SHUTDOWN
# =============================================================================

def request_shutdown(signum: int, frame: Any) -> None:
    """Handle Ctrl+C by finishing the current question before exiting."""
    global shutdown_requested

    if not shutdown_requested:
        shutdown_requested = True
        log_warning("Interrupt received.")
        log_warning("Finishing current question before shutdown.")


def setup_signal_handlers() -> None:
    signal.signal(signal.SIGINT, request_shutdown)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, request_shutdown)


# =============================================================================
# PROCESSING LOGIC
# =============================================================================

def fetch_question(question_entry: dict[str, Any]) -> dict[str, Any]:
    """Fetch and validate a single question from a JSON entry."""
    log_info("Fetching question...")

    if not isinstance(question_entry, dict):
        raise ValueError("Question entry must be a JSON object")

    question_id = question_entry.get("question_id")
    if not question_id:
        raise ValueError("Question entry is missing question_id")

    response = question_entry.get("response")
    if not isinstance(response, dict):
        raise ValueError(f"Question {question_id} is missing a valid response object")

    log_info("Question fetched successfully.")
    log_info(f"Question ID: {question_id}")

    return {
        "question_id": question_id,
        "status_code": question_entry.get("status_code"),
        "response": response,
    }


def run_image_resolution(
    question_entry: dict[str, Any],
    folder_name: str,
    file_qtype: str,
) -> dict[str, Any] | None:
    """Pass a question to image_resolution_engine and return the result."""
    log_info("Sending question to image_resolution_engine.")
    log_info("Image resolution processing started.")

    question_type = question_entry.get("response", {}).get("type")
    question_id = question_entry.get("question_id")

    result = analyze_question(question_entry, question_type, folder_name)

    if not result:
        log_skip(
            question_id=question_id,
            stage="ANALYZER",
            reason="ANALYZER",
            question_type=file_qtype,
            lesson=folder_name,
        )
        log_warning("No output generated for this question.")
    else:
        log_success(
            question_id=question_id,
            widget_type=result.get("widget_type"),
            resolution=result.get("resolution"),
            question_type=file_qtype,
            lesson=folder_name,
        )
        append_resolution_output(result)
        log_info("Output generated in image_resolution_output.")

    log_info("Image resolution processing completed.")
    return result


def process_question(
    question_entry: dict[str, Any],
    folder_name: str,
    file_qtype: str,
    progress: dict[str, Any],
) -> bool:
    """Fetch one question, run resolution + transformation, and save progress."""
    try:
        question = fetch_question(question_entry)
        resolution_result = run_image_resolution(
            question_entry, folder_name, file_qtype
        )

        if resolution_result:
            log_info("Starting image transformation.")
            ensure_directory(TRANSFORMATION_OUTPUT_ROOT)
            process_resolution_output(resolution_result)

        processed_ids = progress.setdefault("processed_question_ids", [])
        if question["question_id"] not in processed_ids:
            processed_ids.append(question["question_id"])

        save_progress(progress)
        log_info("Moving to next question.")
        print()
        return True

    except Exception as error:
        log_error(f"Question processing failed: {error}")
        return False


def process_file(
    folder_name: str,
    file_path: str,
    progress: dict[str, Any],
) -> None:
    """Process all questions in a single JSON file sequentially."""
    file_name = os.path.basename(file_path)
    file_qtype = file_name.replace(".json", "")
    log_info(f"Processing file: {file_name}")

    questions = load_json_file(file_path)
    if questions is None:
        log_warning(f"Skipping invalid file: {file_name}")
        return

    processed_ids = set(progress.get("processed_question_ids", []))
    log_info(f"Found {len(questions)} question(s) in {file_name}")

    for question_entry in questions:
        if shutdown_requested:
            break

        if not isinstance(question_entry, dict):
            log_warning(f"Skipping invalid question entry in {file_name}")
            continue

        question_id = question_entry.get("question_id")
        if question_id in processed_ids:
            log_info(f"Skipping already processed question: {question_id}")
            print()
            continue

        process_question(
            question_entry=question_entry,
            folder_name=folder_name,
            file_qtype=file_qtype,
            progress=progress,
        )

        if shutdown_requested:
            log_info("Current question completed.")
            break


def discover_subject_folders() -> list[str]:
    """Return all subject folders inside the input root."""
    if not os.path.isdir(INPUT_ROOT):
        log_error(f"Input folder not found: {INPUT_ROOT}")
        return []

    folders = []
    for entry in os.scandir(INPUT_ROOT):
        if entry.is_dir():
            folders.append(entry.name)

    folders.sort()
    return folders


def discover_json_files(folder_path: str) -> list[str]:
    """Return all JSON files inside a subject folder."""
    if not os.path.isdir(folder_path):
        log_warning(f"Folder not found: {folder_path}")
        return []

    files = []
    for entry in os.scandir(folder_path):
        if entry.is_file() and entry.name.lower().endswith(".json"):
            files.append(entry.path)

    files.sort()
    return files


def run_migration() -> None:
    """Main entry point for the image migration process."""
    log_info("Starting image migration process...")
    setup_signal_handlers()

    ensure_directory(RESOLUTION_OUTPUT_ROOT)
    progress = load_progress()

    subject_folders = discover_subject_folders()
    if not subject_folders:
        log_warning("No subject folders found. Nothing to process.")
        return

    log_info(f"Found {len(subject_folders)} folders.")

    for folder_name in subject_folders:
        if shutdown_requested:
            break

        log_info(f"Processing folder: {folder_name}")
        folder_path = os.path.join(INPUT_ROOT, folder_name)
        json_files = discover_json_files(folder_path)

        if not json_files:
            log_warning(f"No JSON files found in folder: {folder_name}")
            continue

        for file_path in json_files:
            if shutdown_requested:
                break

            process_file(folder_name, file_path, progress)

    if shutdown_requested:
        log_info("Graceful shutdown completed.")
    else:
        log_info("Image migration process completed.")


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    try:
        run_migration()
    except KeyboardInterrupt:
        if not shutdown_requested:
            shutdown_requested = True
            log_warning("Interrupt received.")
            log_warning("Finishing current question before shutdown.")
        log_info("Graceful shutdown completed.")
        sys.exit(0)
