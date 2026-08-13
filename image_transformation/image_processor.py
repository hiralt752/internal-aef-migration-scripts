"""
Locate and transform images using image_resolution_engine output.
"""

import fnmatch
import urllib.request
import urllib.error
import os
import shutil  # For copying audio/video files without transformation
from typing import Any
from PIL import Image


from image_transformation.image_transformation import (
    log_error,
    log_warning,
    transform_image,
)

SCRIPTS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MEDIA_ROOT = r"D:\media"
TRANSFORMATION_DIR = os.path.join(SCRIPTS_DIR, "image_transformation")
TRANSFORMATION_OUTPUT_ROOT = os.path.join(
    TRANSFORMATION_DIR, "image_transformation_output"
)

def _is_non_image_media(entry: dict) -> bool:
    """Return True if entry is audio or video.

    Checks the 'content_type' field and falls back to the file extension in 'src'.
    Used to skip non‑image entries during image transformation passes.
    """
    content_type = entry.get("content_type", "IMAGE").upper()
    if content_type in {"AUDIO", "VIDEO"}:
        return True
    src = entry.get("src", "")
    if not src:
        return False
    ext = os.path.splitext(src)[1].lower()
    return ext in {".mp3", ".wav", ".mp4", ".avi", ".mov", ".mkv"}


def extract_image_name(src: str) -> str:
    """Extract the file name from a src path."""
    if not src:
        return ""

    normalized = src.replace("\\", "/").split("?")[0]
    return os.path.basename(normalized)


def find_image_file(question_id: str, image_name: str) -> str | None:
    """Find an image in the media repository using {question_id}*{image_name}."""
    search_dir = MEDIA_ROOT

    if not os.path.isdir(search_dir):
        log_warning(f"Media folder not found: {search_dir}")
        return None

    pattern = f"{question_id}*{image_name}"

    for dirpath, _, filenames in os.walk(search_dir):
        for filename in filenames:
            if fnmatch.fnmatch(filename, pattern):
                return os.path.join(dirpath, filename)

    return None


def build_output_path(category: str, source_filename: str) -> str:
    """Build the subject-wise output path for a transformed image."""
    output_dir = os.path.join(TRANSFORMATION_OUTPUT_ROOT, category)
    os.makedirs(output_dir, exist_ok=True)
    return os.path.join(output_dir, source_filename)


def _is_svg(src: str) -> bool:
    """Return True if entry is an SVG image."""
    if not src:
        return False
    clean_src = src.split("?")[0]
    return clean_src.lower().endswith(".svg")


def has_transparent_pixels(filepath: str) -> bool:
    """Check if a PNG image contains actual transparent pixels."""
    try:
        with Image.open(filepath) as img:
            if img.mode not in ('RGBA', 'LA') and not (img.mode == 'P' and 'transparency' in img.info):
                return False
            rgba = img.convert("RGBA")
            alpha = rgba.split()[-1]
            min_val, max_val = alpha.getextrema()
            return min_val < 255
    except Exception:
        return False


def transform_and_save(
    question_id: str,
    category: str,
    src: str,
    target_width: int,
    target_height: int,
) -> bool | None:
    """Locate one image locally and transform it. No network fallback.

    Returns True on success, False on a recoverable per-item failure (bad src,
    transform error), or None if the file could not be found locally at all -
    callers must treat None as "ignore the whole question", not just this item.
    """
    if not src:
        return False

    image_name = extract_image_name(src)
    if not image_name:
        log_warning(f"Could not extract image name from src: {src}")
        return False

    image_path = find_image_file(question_id, image_name)
    if not image_path:
        log_warning(f"Media not found locally, ignoring question: {src}")
        return None

    out_basename = os.path.basename(image_path)
    name_without_ext, ext = os.path.splitext(out_basename)
    if has_transparent_pixels(image_path):
        out_basename = f"{name_without_ext}.jpg"
    elif ext.lower() in (".webp", ".jfif"):
        out_basename = f"{name_without_ext}.png"
    output_path = build_output_path(category, out_basename)

    try:
        transform_image(image_path, output_path, target_width, target_height)
    except Exception as error:
        log_error(f"Image transformation failed: {error}")
        return False

    return True


def process_media_only(
    question_id: str,
    category: str,
    src: str,
) -> bool:
    """Locate one audio/video file, download if missing, and save to transformation output directory."""
    import shutil
    if not src:
        return False

    media_name = extract_image_name(src)
    if not media_name:
        log_warning(f"Could not extract media name from src: {src}")
        return False

    media_path = find_image_file(question_id, media_name)
    if not media_path:
        clean_src = src.replace('../', '')
        if clean_src.startswith('./'):
            clean_src = clean_src[2:]
        url = f"https://shared.alefed.com/{clean_src}"
        
        env_file = os.path.join(SCRIPTS_DIR, ".env")
        cookie_val = ""
        bearer_val = ""
        if os.path.isfile(env_file):
            with open(env_file, "r", encoding="utf-8") as f:
                for line in f:
                    if line.startswith("YOUR_ASSETS_COOKIE="):
                        cookie_val = line.strip().split("=", 1)[1].strip('"\'')
                    elif "BEARER_TOKEN" in line:
                        parts = line.strip().split("=", 1)
                        if len(parts) == 2:
                            bearer_val = parts[1].strip().strip('"\'')
        
        download_dir = os.path.join(SCRIPTS_DIR, "downloaded_images", category)
        os.makedirs(download_dir, exist_ok=True)
        download_path = os.path.join(download_dir, f"{question_id}_{media_name}")
        
        req = urllib.request.Request(url)
        if cookie_val:
            req.add_header('cookie', cookie_val)
        if bearer_val:
            req.add_header('Authorization', bearer_val)
        
        try:
            with urllib.request.urlopen(req) as response:
                with open(download_path, "wb") as out_file:
                    out_file.write(response.read())
            media_path = download_path
        except urllib.error.HTTPError as e:
            log_error(f"Failed to download media {url}: HTTP {e.code} {e.reason}")
            _append_media_failed(question_id, url, e.code)
            _append_ignore_question(question_id)
            raise MediaDownloadFailed(url)
        except urllib.error.URLError as e:
            log_error(f"Failed to download media {url}: {e.reason}")
            _append_media_failed(question_id, url, "URL_ERROR")
            _append_ignore_question(question_id)
            raise MediaDownloadFailed(url)
        except Exception as e:
            log_error(f"Failed to download media {url}: {e}")
            _append_media_failed(question_id, url, "UNKNOWN_ERROR")
            _append_ignore_question(question_id)
            raise MediaDownloadFailed(url)

    output_path = build_output_path(category, os.path.basename(media_path))
    
    try:
        shutil.copy2(media_path, output_path)
    except Exception as error:
        log_error(f"Media copy failed: {error}")
        return False

    return True


def copy_media_and_save(question_id: str, category: str, src: str) -> bool | None:
    """Copy audio/video files without transformation.

    Returns True on success, None if the media cannot be located (even after download), and False on other failures.
    """
    if not src:
        return False
    # Locate the media file locally
    media_name = extract_image_name(src)
    if not media_name:
        log_warning(f"Could not extract media name from src: {src}")
        return False
    media_path = find_image_file(question_id, media_name)
    if not media_path:
        # Attempt to download via process_media_only
        if not process_media_only(question_id, category, src):
            return None
        media_path = find_image_file(question_id, media_name)
        if not media_path:
            return None
    output_path = build_output_path(category, os.path.basename(media_path))
    try:
        shutil.copy2(media_path, output_path)
    except Exception as error:
        log_error(f"Media copy failed: {error}")
        return False
    return True


def process_resolution_output(resolution_result: dict[str, Any]) -> None:
    """
    Process all images described in one image_resolution_engine result.

    Priority:
    1. image_audit (uses per-record max_width / max_height)
    2. question_images
    3. option_images

    Returns None if every media item was handled normally (including per-item
    soft failures that were logged and skipped). Returns a reason string, and
    stops processing further media, the moment a media file can't be found
    locally - the caller must then ignore the whole question, not just that item.
    """
    if not resolution_result:
        return

    question_id = resolution_result.get("question_id")
    category = resolution_result.get("category")

    if not question_id or not category:
        log_error("Resolution result is missing question_id or category.")
        return None

    resolution = resolution_result.get("resolution") or {}

    # Process all audio/video assets immediately
    audios = resolution_result.get("question_audios") or []
    videos = resolution_result.get("question_videos") or []
    for entry in audios + videos:
        process_media_only(question_id, category, entry.get("src"))

    # Process audits (strictly images now)
    for audit_entry in (resolution_result.get("image_audit") or []):
        src = audit_entry.get("src")
        target_width = audit_entry.get("max_width")
        target_height = audit_entry.get("max_height")

        if not src:
            continue

        if _is_non_image_media(audit_entry):
            continue

        if src.startswith("data:") or src.startswith("http://") or src.startswith("https://"):
            continue

        if _is_svg(src):
            return f"Question contains SVG file: {src}"

        if target_width is None or target_height is None:
            log_warning(f"Skipping audit image with missing dimensions: {src}")
            continue

        if transform_and_save(
            question_id=question_id,
            category=category,
            src=src,
            target_width=int(target_width),
            target_height=int(target_height),
        ) is None:
            return f"local media file not found: {src}"

    # Process question and option images (strictly images now)
    question_images = resolution_result.get("question_images") or []
    option_images = resolution_result.get("option_images") or []

    has_question_images = bool(question_images)
    has_option_images = bool(option_images)

    if has_question_images and has_option_images:
        question_width = resolution.get("max_width")
        question_height = resolution.get("max_height")
        option_width = resolution.get("option_width") or resolution.get("option_image_width")
        option_height = resolution.get("option_height") or resolution.get("option_image_height")

        for image_entry in question_images:
            src = image_entry.get("src")
            if _is_non_image_media(image_entry):
                continue
            if src and (src.startswith("data:") or src.startswith("http://") or src.startswith("https://")):
                continue
            if _is_svg(src):
                return f"Question contains SVG file: {src}"
            if question_width is None or question_height is None:
                log_warning(f"Skipping question image with missing resolution: {src}")
                continue

            if transform_and_save(
                question_id=question_id,
                category=category,
                src=src,
                target_width=int(question_width),
                target_height=int(question_height),
            ) is None:
                return f"local media file not found: {src}"

        for image_entry in option_images:
            src = image_entry.get("src")
            if _is_non_image_media(image_entry):
                continue
            if src and (src.startswith("data:") or src.startswith("http://") or src.startswith("https://")):
                continue
            if _is_svg(src):
                return f"Question contains SVG file: {src}"
            if option_width is None or option_height is None:
                log_warning(f"Skipping option image with missing resolution: {src}")
                continue

            if transform_and_save(
                question_id=question_id,
                category=category,
                src=src,
                target_width=int(option_width),
                target_height=int(option_height),
            ) is None:
                return f"local media file not found: {src}"

    elif has_question_images or has_option_images:
        target_width = resolution.get("max_width")
        target_height = resolution.get("max_height")

        if target_width is None or target_height is None:
            log_warning("Skipping images because resolution max_width/max_height is missing.")
        else:
            for image_entry in question_images + option_images:
                src = image_entry.get("src")
                if _is_non_image_media(image_entry):
                    continue
                if src and (src.startswith("data:") or src.startswith("http://") or src.startswith("https://")):
                    continue
                if _is_svg(src):
                    return f"Question contains SVG file: {src}"
                if transform_and_save(
                    question_id=question_id,
                    category=category,
                    src=src,
                    target_width=int(target_width),
                    target_height=int(target_height),
                ) is None:
                    return f"local media file not found: {src}"

    # Copy audio and video files without transformation
    for media_entry in (resolution_result.get("question_audios") or []):
        src = media_entry.get("src")
        if not src:
            continue
        if src.startswith("data:") or src.startswith("http://") or src.startswith("https://"):
            continue
        if copy_media_and_save(question_id, category, src) is None:
            return f"local media file not found: {src}"

    for media_entry in (resolution_result.get("question_videos") or []):
        src = media_entry.get("src")
        if not src:
            continue
        if src.startswith("data:") or src.startswith("http://") or src.startswith("https://"):
            continue
        if copy_media_and_save(question_id, category, src) is None:
            return f"local media file not found: {src}"

    return None
