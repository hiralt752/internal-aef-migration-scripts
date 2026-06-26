"""
Image migration script.

Fetches questions sequentially from core_seperated_data_input and passes each
one to image_resolution_engine for processing.
"""

import json
import os
import re
import signal
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

# =============================================================================
# CONFIGURATION
# =============================================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INPUT_ROOT = os.path.join(BASE_DIR, "core_seperated_data_input")
ENGINE_DIR = os.path.join(BASE_DIR, "image_resolution_engine")
# TRANSFORMATION_DIR = os.path.join(BASE_DIR, "image_transformation")
# RESOLUTION_OUTPUT_ROOT = os.path.join(ENGINE_DIR, "image_resolution_output")
RESOLUTION_OUTPUT_ROOT = os.path.join(BASE_DIR, "image_resolution_engine/image_resolution_output")

# TRANSFORMATION_OUTPUT_ROOT = os.path.join(
#     TRANSFORMATION_DIR, "image_transformation_output"
# )
TRANSFORMATION_OUTPUT_ROOT = os.path.join(
    BASE_DIR, "image_transformation/image_transformation_output"
)
MIGRATION_OUTPUT_ROOT = os.path.join(BASE_DIR, "image_migration_output")
PROGRESS_FILE = os.path.join(RESOLUTION_OUTPUT_ROOT, "progress.json")
UPLOAD_DIR = os.path.join(BASE_DIR, "image_upload")
STEP1_OUTPUT = os.path.join(UPLOAD_DIR, "step_1.json")
STEP2_OUTPUT = os.path.join(UPLOAD_DIR, "step_2.json")
STEP3_OUTPUT = os.path.join(UPLOAD_DIR, "step_3.json")
IMAGE_MAPPING_FILE = os.path.join(UPLOAD_DIR, "image_mapping.json")

URL = "https://ccl-rc-az.nprd.alefed.com"  #DEV URL
# URL = "https://shared.alefed.com"          #PROD URL

PRESIGNED_URL_API = (f"{URL}/authoring-content-service/api/assets/presigned-upload-url")
CREATE_PUBLISH_API = (f"{URL}/authoring-content-service/api/assets/create-and-publish")

# PRESIGNED_URL_API = (
#     "https://ccl-rc-az.nprd.alefed.com"
#     "/authoring-content-service/api/assets/presigned-upload-url"
# )

# CREATE_PUBLISH_API = (
#     "https://ccl-rc-az.nprd.alefed.com"
#     "/authoring-content-service/api/assets/create-and-publish"
# )

CONTENT_TYPE_MAP = {
    ".jpg":  "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png":  "image/png",
    ".gif":  "image/gif",
    ".webp": "image/webp",
    ".svg":  "image/svg+xml",
}

_UUID_RE = re.compile(
    r"^([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})",
    re.IGNORECASE,
)

# Allow imports from image_resolution_engine (analyzers, helpers, etc.)
# sys.path.insert(0, ENGINE_DIR)
# sys.path.insert(0, BASE_DIR)

sys.path.insert(0, os.path.join(BASE_DIR, "image_resolution_engine"))
sys.path.insert(0, BASE_DIR)

from analyzers.dispatcher import analyze_question
from helpers.resolution_debugger import log_skip, log_success
from image_transformation.image_processor import MediaDownloadFailed, process_resolution_output

# =============================================================================
# GLOBAL STATE
# =============================================================================

shutdown_requested = False
_stats: dict[str, int] = {"ok": 0, "skip": 0, "abort": 0}


# =============================================================================
# LOGGING
# =============================================================================

def log_info(message: str) -> None:
    print(f"[INFO]  {message}")


def log_warning(message: str) -> None:
    print(f"[WARNING] {message}")


def log_error(message: str) -> None:
    print(f"[ERROR] {message}")


def log_ok(message: str) -> None:
    print(f"[OK]    {message}")


def log_skip_line(message: str) -> None:
    print(f"[SKIP]  {message}")


def log_abort(message: str) -> None:
    print(f"[ABORT] {message}")


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


def ensure_directory(directory_path: str) -> None:
    """Create a directory if it does not already exist."""
    if not directory_path:
        return
    normalized_path = os.path.normpath(os.path.abspath(directory_path))
    if not os.path.isdir(normalized_path):
        os.makedirs(normalized_path, exist_ok=True)


def append_resolution_output(result: dict[str, Any]) -> None:
    """Append one engine result to image_resolution_output."""
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


# =============================================================================
# GRACEFUL SHUTDOWN
# =============================================================================

def request_shutdown(signum: int, frame: Any) -> None:
    """Handle Ctrl+C by finishing the current question before exiting."""
    global shutdown_requested

    if not shutdown_requested:
        shutdown_requested = True
        log_warning("Interrupt received — finishing current question before shutdown.")


def setup_signal_handlers() -> None:
    signal.signal(signal.SIGINT, request_shutdown)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, request_shutdown)


# =============================================================================
# PROCESSING LOGIC
# =============================================================================

def fetch_question(question_entry: dict[str, Any]) -> dict[str, Any]:
    """Fetch and validate a single question from a JSON entry."""
    if not isinstance(question_entry, dict):
        raise ValueError("Question entry must be a JSON object")

    question_id = question_entry.get("question_id")
    if not question_id:
        raise ValueError("Question entry is missing question_id")

    response = question_entry.get("response")
    if not isinstance(response, dict):
        raise ValueError(f"Question {question_id} is missing a valid response object")

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
    else:
        log_success(
            question_id=question_id,
            widget_type=result.get("widget_type"),
            resolution=result.get("resolution"),
            question_type=file_qtype,
            lesson=folder_name,
        )
        append_resolution_output(result)

    return result


def process_question(
    question_entry: dict[str, Any],
    folder_name: str,
    file_qtype: str,
    progress: dict[str, Any],
) -> bool:
    """Fetch one question, run resolution + transformation, and save progress."""
    global _stats

    try:
        question = fetch_question(question_entry)
        question_id = question["question_id"]
        resolution_result = run_image_resolution(question_entry, folder_name, file_qtype)

        if not resolution_result:
            log_skip_line(f"{question_id} — no images found")
            _stats["skip"] += 1
        else:
            widget_type = resolution_result.get("widget_type", "unknown")
            image_count = (
                len(resolution_result.get("image_audit") or [])
                + len(resolution_result.get("question_images") or [])
                + len(resolution_result.get("option_images") or [])
            )

            ensure_directory(TRANSFORMATION_OUTPUT_ROOT)
            process_resolution_output(resolution_result)

            log_ok(f"{question_id} — {file_qtype} | {widget_type} | {image_count} image(s)")
            _stats["ok"] += 1

        processed_ids = progress.setdefault("processed_question_ids", [])
        if question_id not in processed_ids:
            processed_ids.append(question_id)

        save_progress(progress)
        return True

    except MediaDownloadFailed as e:
        question_id = question_entry.get("question_id", "unknown")
        log_abort(f"{question_id} — download failed ({e}) → logged to media_failed.json")
        _stats["abort"] += 1
        return False

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

    questions = load_json_file(file_path)
    if questions is None:
        log_warning(f"Skipping invalid file: {file_name}")
        return

    processed_ids = set(progress.get("processed_question_ids", []))
    print(f"\n[INFO]  {folder_name} / {file_name} — {len(questions)} question(s)")

    for question_entry in questions:
        if shutdown_requested:
            break

        if not isinstance(question_entry, dict):
            log_warning(f"Skipping invalid question entry in {file_name}")
            continue

        question_id = question_entry.get("question_id")
        if question_id in processed_ids:
            log_skip_line(f"{question_id} — already processed")
            continue

        process_question(
            question_entry=question_entry,
            folder_name=folder_name,
            file_qtype=file_qtype,
            progress=progress,
        )

        if shutdown_requested:
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


# =============================================================================
# STEP 1 — PRESIGNED UPLOAD URL
# =============================================================================

def _load_env() -> dict[str, str]:
    env_file = os.path.join(BASE_DIR, ".env")
    values: dict[str, str] = {}
    if not os.path.isfile(env_file):
        return values
    with open(env_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                key, _, val = line.partition("=")
                values[key.strip()] = val.strip().strip('"\'')
    return values



def _call_presigned_api(
    file_name: str,
    content_type: str,
    file_size: int,
    bearer_token: str,
    tenant_id: str,
) -> dict[str, Any]:
    params = urllib.parse.urlencode({
        "fileName": file_name,
        "contentType": content_type,
        "fileSize": file_size,
    })
    req = urllib.request.Request(f"{PRESIGNED_URL_API}?{params}")
    req.add_header("Authorization", f"Bearer {bearer_token}")
    req.add_header("X-tenantId", tenant_id)
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def run_step1() -> None:
    """Request a presigned upload URL for every transformed image."""
    log_info("Step 1 — Requesting presigned upload URLs...")

    env = _load_env()
    bearer_token = env.get("BEARER_TOKEN", "")
    tenant_id = env.get("CCL_TENANT_ID", "shared")

    if not bearer_token:
        log_error("BEARER_TOKEN not set in .env — cannot call presigned URL API.")
        return

    if not os.path.isdir(TRANSFORMATION_OUTPUT_ROOT):
        log_error(f"Transformation output not found: {TRANSFORMATION_OUTPUT_ROOT}")
        return

    ensure_directory(UPLOAD_DIR)

    results: dict[str, list[dict[str, Any]]] = {}
    if os.path.isfile(STEP1_OUTPUT):
        try:
            with open(STEP1_OUTPUT, "r", encoding="utf-8") as f:
                results = json.load(f)
        except (json.JSONDecodeError, OSError):
            pass

    processed = skipped = failed = 0

    for category in sorted(os.listdir(TRANSFORMATION_OUTPUT_ROOT)):
        category_dir = os.path.join(TRANSFORMATION_OUTPUT_ROOT, category)
        if not os.path.isdir(category_dir):
            continue

        for file_name in sorted(os.listdir(category_dir)):
            file_path = os.path.join(category_dir, file_name)
            if not os.path.isfile(file_path):
                continue

            match = _UUID_RE.match(file_name)
            if not match:
                log_warning(f"Cannot extract question_id from: {file_name}")
                continue
            question_id = match.group(1)

            already_done = any(
                e.get("file_name") == file_name
                for e in results.get(question_id, [])
            )
            if already_done:
                skipped += 1
                continue

            ext = os.path.splitext(file_name)[1].lower()
            content_type = CONTENT_TYPE_MAP.get(ext, "application/octet-stream")
            file_size = os.path.getsize(file_path)

            try:
                response = _call_presigned_api(
                    file_name=file_name,
                    content_type=content_type,
                    file_size=file_size,
                    bearer_token=bearer_token,
                    tenant_id=tenant_id,
                )

                results.setdefault(question_id, []).append({
                    "file_name": file_name,
                    "file_path": file_path,
                    "content_type": content_type,
                    "file_size": file_size,
                    "response": response,
                })
                log_ok(f"{file_name} ({file_size} bytes) → presigned URL obtained")
                processed += 1

            except urllib.error.HTTPError as e:
                log_error(f"Presigned URL failed for {file_name}: {e}")
                results.setdefault(question_id, []).append({
                    "status_code": e.code,
                    "status": "failed",
                    "error": e.reason,
                    "file_name": file_name,
                    "content_type": content_type,
                })
                failed += 1
            except Exception as e:
                log_error(f"Presigned URL failed for {file_name}: {e}")
                results.setdefault(question_id, []).append({
                    "status_code": None,
                    "status": "failed",
                    "error": str(e),
                    "file_name": file_name,
                    "content_type": content_type,
                })
                failed += 1

    with open(STEP1_OUTPUT, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print()
    log_info(
        f"Step 1 complete. Processed: {processed} | "
        f"Skipped: {skipped} | Failed: {failed}"
    )
    log_info(f"Output → {STEP1_OUTPUT}")


# =============================================================================
# STEP 2 — UPLOAD IMAGE TO PRESIGNED URL
# =============================================================================

def run_step2() -> None:
    """PUT each transformed image to its presigned URL from Step 1."""
    log_info("Step 2 — Uploading images to presigned URLs...")

    if not os.path.isfile(STEP1_OUTPUT):
        log_error(f"step_1.json not found — run Step 1 first.")
        return

    with open(STEP1_OUTPUT, "r", encoding="utf-8") as f:
        step1_data: dict[str, list[dict[str, Any]]] = json.load(f)

    results: dict[str, list[dict[str, Any]]] = {}
    if os.path.isfile(STEP2_OUTPUT):
        try:
            with open(STEP2_OUTPUT, "r", encoding="utf-8") as f:
                results = json.load(f)
        except (json.JSONDecodeError, OSError):
            pass

    processed = skipped = failed = 0

    for question_id, entries in step1_data.items():
        for entry in entries:
            file_name = entry.get("file_name", "")
            file_path = entry.get("file_path", "")
            content_type = entry.get("content_type", "application/octet-stream")
            upload_url = (
                entry.get("response", {})
                    .get("responce", {})
                    .get("presignedUrl", {})
                    .get("url", "")
            )

            if not upload_url:
                log_warning(f"No presigned URL for {file_name} — skipping.")
                failed += 1
                continue

            already_done = any(
                e.get("file_name") == file_name
                for e in results.get(question_id, [])
            )
            if already_done:
                skipped += 1
                continue

            try:
                if not os.path.isfile(file_path):
                    log_error(f"Image file not found: {file_path}")
                    failed += 1
                    continue

                with open(file_path, "rb") as img_f:
                    image_data = img_f.read()

                req = urllib.request.Request(upload_url, data=image_data, method="PUT")
                req.add_header("x-ms-blob-type", "BlockBlob")
                req.add_header("Content-Type", content_type)

                with urllib.request.urlopen(req) as resp:
                    status_code = resp.status

                results.setdefault(question_id, []).append({
                    "file_name": file_name,
                    "upload_url": upload_url,
                    "status_code": status_code,
                    "success": status_code in (200, 201),
                })

                log_ok(f"{file_name} → HTTP {status_code}")
                processed += 1

            except Exception as e:
                log_error(f"Upload failed for {file_name}: {e}")
                results.setdefault(question_id, []).append({
                    "file_name": file_name,
                    "upload_url": upload_url,
                    "status_code": None,
                    "success": False,
                    "error": str(e),
                })
                failed += 1

    with open(STEP2_OUTPUT, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print()
    log_info(
        f"Step 2 complete. Uploaded: {processed} | "
        f"Skipped: {skipped} | Failed: {failed}"
    )
    log_info(f"Output → {STEP2_OUTPUT}")


# =============================================================================
# STEP 3 — CREATE AND PUBLISH ASSET
# =============================================================================

def run_step3() -> None:
    """POST create-and-publish for every image that was uploaded in Step 2."""
    log_info("Step 3 — Creating and publishing assets...")

    if not os.path.isfile(STEP1_OUTPUT):
        log_error("step_1.json not found — run Step 1 first.")
        return

    if not os.path.isfile(STEP2_OUTPUT):
        log_error("step_2.json not found — run Step 2 first.")
        return

    with open(STEP1_OUTPUT, "r", encoding="utf-8") as f:
        step1_data: dict[str, list[dict[str, Any]]] = json.load(f)

    with open(STEP2_OUTPUT, "r", encoding="utf-8") as f:
        step2_data: dict[str, list[dict[str, Any]]] = json.load(f)

    results: dict[str, list[dict[str, Any]]] = {}
    if os.path.isfile(STEP3_OUTPUT):
        try:
            with open(STEP3_OUTPUT, "r", encoding="utf-8") as f:
                results = json.load(f)
        except (json.JSONDecodeError, OSError):
            pass

    env = _load_env()
    bearer_token = env.get("BEARER_TOKEN", "")
    tenant_id = env.get("CCL_TENANT_ID", "shared")

    if not bearer_token:
        log_error("BEARER_TOKEN not set in .env — cannot call create-and-publish API.")
        return

    processed = skipped = failed = 0

    for question_id, entries in step1_data.items():
        # Only process images that were successfully uploaded in Step 2
        step2_entries = step2_data.get(question_id, [])
        successful_uploads = {
            e["file_name"] for e in step2_entries if e.get("success")
        }

        eligible = [e for e in entries if e.get("file_name") in successful_uploads]
        total = len(eligible)

        for idx, entry in enumerate(eligible, start=1):
            file_name = entry.get("file_name", "")
            step1_resp = entry.get("response", {}).get("responce", {})
            file_id = step1_resp.get("fileId", "")
            upload_id = step1_resp.get("uploadId", "")

            title = (
                f"{question_id}_IMG"
                if total == 1
                else f"{question_id}_IMG_{idx}"
            )

            already_done = any(
                e.get("file_name") == file_name
                for e in results.get(question_id, [])
            )
            if already_done:
                skipped += 1
                continue

            try:
                body = json.dumps({
                    "fileName": file_name,
                    "fileId": file_id,
                    "uploadId": upload_id,
                    "title": title,
                    "description": title,
                    "type": "IMAGE",
                    "metadata": [],
                    "systemMetadata": [],
                    "tagIds": [],
                }).encode("utf-8")

                req = urllib.request.Request(CREATE_PUBLISH_API, data=body, method="POST")
                req.add_header("Authorization", f"Bearer {bearer_token}")
                req.add_header("X-tenantId", tenant_id)
                req.add_header("Content-Type", "application/json")
                req.add_header("Origin", "https://ccl-rc-az.nprd.alefed.com")
                req.add_header("Referer", "https://ccl-rc-az.nprd.alefed.com/")

                with urllib.request.urlopen(req) as resp:
                    response = json.loads(resp.read())

                results.setdefault(question_id, []).append({
                    "file_name": file_name,
                    "title": title,
                    "response": response,
                })

                log_ok(f"{file_name} → asset published as '{title}'")
                processed += 1

            except Exception as e:
                log_error(f"Create-and-publish failed for {file_name}: {e}")
                results.setdefault(question_id, []).append({
                    "file_name": file_name,
                    "title": title,
                    "response": None,
                    "error": str(e),
                })
                failed += 1

    with open(STEP3_OUTPUT, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print()
    log_info(
        f"Step 3 complete. Published: {processed} | "
        f"Skipped: {skipped} | Failed: {failed}"
    )
    log_info(f"Output → {STEP3_OUTPUT}")


# =============================================================================
# STEP 4 — SWAP OLD SRC URLS WITH ASSET IDs, WRITE MODIFIED QUESTIONS
# =============================================================================

def run_step4() -> None:
    """Replace old image src URLs with assetIds and write modified question JSONs."""
    log_info("Step 4 — Swapping image URLs with asset IDs...")

    if not os.path.isfile(STEP3_OUTPUT):
        log_error("step_3.json not found — run Step 3 first.")
        return

    with open(STEP3_OUTPUT, "r", encoding="utf-8") as f:
        step3_data: dict[str, list[dict[str, Any]]] = json.load(f)

    # Build: question_id → { file_name → assetId }
    file_asset_map: dict[str, dict[str, str]] = {}
    for question_id, entries in step3_data.items():
        for entry in entries:
            file_name = entry.get("file_name", "")
            asset_id = (
                entry.get("response", {})
                     .get("responce", {})
                     .get("assetId", "")
            )
            if file_name and asset_id:
                file_asset_map.setdefault(question_id, {})[file_name] = asset_id

    if not file_asset_map:
        log_warning("No asset IDs found in step_3.json — nothing to swap.")
        return

    # Load resolution outputs → question_id → resolution entry (has src URLs + category + source_type)
    resolution_by_qid: dict[str, dict[str, Any]] = {}
    for fname in sorted(os.listdir(RESOLUTION_OUTPUT_ROOT)):
        if not fname.endswith(".json") or fname == "progress.json":
            continue
        try:
            with open(os.path.join(RESOLUTION_OUTPUT_ROOT, fname), "r", encoding="utf-8") as f:
                for entry in json.load(f):
                    qid = entry.get("question_id")
                    if qid:
                        resolution_by_qid[qid] = entry
        except (json.JSONDecodeError, OSError):
            pass

    # Build: question_id → { original_src → assetId }
    # Match by: file_name ends with the basename of the src URL
    src_asset_map: dict[str, dict[str, str]] = {}
    for question_id, q_file_map in file_asset_map.items():
        res_entry = resolution_by_qid.get(question_id, {})

        all_srcs: list[str] = []
        for key in ("question_images", "option_images", "image_audit"):
            for img in (res_entry.get(key) or []):
                src = img.get("src")
                if src:
                    all_srcs.append(src)

        mapping: dict[str, str] = {}
        for file_name, asset_id in q_file_map.items():
            for src in all_srcs:
                src_basename = os.path.basename(src.split("?")[0])
                if file_name.endswith(src_basename):
                    mapping[src] = asset_id
                    break

        src_asset_map[question_id] = mapping

    # Group questions by (category, source_type) to write one output file per input file
    output_groups: dict[tuple[str, str], list[str]] = {}
    for question_id in file_asset_map:
        res_entry = resolution_by_qid.get(question_id, {})
        category = res_entry.get("category", "")
        source_type = res_entry.get("source_type", "")
        if category and source_type:
            output_groups.setdefault((category, source_type), []).append(question_id)

    image_mapping: dict[str, dict[str, str]] = {}
    processed_files = 0
    swapped_total = 0

    for (category, source_type), question_ids in sorted(output_groups.items()):
        input_file = os.path.join(INPUT_ROOT, category, f"{category}_{source_type}.json")
        output_dir = os.path.join(MIGRATION_OUTPUT_ROOT, category)
        output_file = os.path.join(output_dir, f"{category}_{source_type}.json")

        questions = load_json_file(input_file)
        if questions is None:
            log_warning(f"Input file not found: {input_file}")
            continue

        modified_questions = []
        for q in questions:
            qid = q.get("question_id")
            src_map = src_asset_map.get(qid, {})

            if src_map:
                q_str = json.dumps(q, ensure_ascii=False)
                for src, asset_id in src_map.items():
                    q_str = q_str.replace(src, asset_id)
                q = json.loads(q_str)

                image_mapping.setdefault(qid, {}).update(file_asset_map.get(qid, {}))
                log_ok(f"{qid} — {len(src_map)} URL(s) replaced")
                swapped_total += len(src_map)

            modified_questions.append(q)

        ensure_directory(output_dir)
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(modified_questions, f, ensure_ascii=False, indent=2)

        log_info(f"Saved: {category}/{category}_{source_type}.json")
        processed_files += 1

    ensure_directory(UPLOAD_DIR)
    with open(IMAGE_MAPPING_FILE, "w", encoding="utf-8") as f:
        json.dump(image_mapping, f, ensure_ascii=False, indent=2)

    print()
    log_info(
        f"Step 4 complete. Files written: {processed_files} | "
        f"URLs swapped: {swapped_total}"
    )
    log_info(f"Mapping → {IMAGE_MAPPING_FILE}")


def run_migration() -> None:
    """Main entry point for the image migration process."""
    global _stats
    _stats = {"ok": 0, "skip": 0, "abort": 0}

    log_info("Starting image migration...")
    setup_signal_handlers()

    ensure_directory(RESOLUTION_OUTPUT_ROOT)
    progress = load_progress()

    subject_folders = discover_subject_folders()
    if not subject_folders:
        log_warning("No subject folders found. Nothing to process.")
        return

    for folder_name in subject_folders:
        if shutdown_requested:
            break

        folder_path = os.path.join(INPUT_ROOT, folder_name)
        json_files = discover_json_files(folder_path)

        if not json_files:
            log_warning(f"No JSON files found in folder: {folder_name}")
            continue

        for file_path in json_files:
            if shutdown_requested:
                break
            process_file(folder_name, file_path, progress)

    print()
    if shutdown_requested:
        log_info(
            f"Shutdown. Processed: {_stats['ok']} | "
            f"Skipped: {_stats['skip']} | Aborted: {_stats['abort']}"
        )
    else:
        log_info(
            f"Migration complete. Processed: {_stats['ok']} | "
            f"Skipped: {_stats['skip']} | Aborted: {_stats['abort']}"
        )


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    try:
        run_migration()
        print()
        run_step1()
        print()
        run_step2()
        print()
        run_step3()
        print()
        run_step4()
    except KeyboardInterrupt:
        if not shutdown_requested:
            shutdown_requested = True
        log_warning("Interrupt received — finishing current question before shutdown.")
        log_info(
            f"Shutdown. Processed: {_stats['ok']} | "
            f"Skipped: {_stats['skip']} | Aborted: {_stats['abort']}"
        )
        sys.exit(0)
