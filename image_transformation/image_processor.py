"""
Locate and transform images using image_resolution_engine output.
"""

import fnmatch
import os
import shutil  # For copying audio/video files without transformation
from typing import Any

from image_transformation.image_transformation import (
    log_error,
    log_warning,
    transform_image,
)

SCRIPTS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MEDIA_ROOT = r"C:\Users\PC\Documents\project_migration\media"
TRANSFORMATION_DIR = os.path.join(SCRIPTS_DIR, "image_transformation")
TRANSFORMATION_OUTPUT_ROOT = os.path.join(
    TRANSFORMATION_DIR, "image_transformation_output"
)


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

    output_path = build_output_path(category, os.path.basename(image_path))

    try:
        transform_image(image_path, output_path, target_width, target_height)
    except Exception as error:
        log_error(f"Image transformation failed: {error}")
        return False

    return True


def copy_media_and_save(question_id: str, category: str, src: str) -> bool | None:
    """Locate an audio or video file locally and copy it to the output directory.
    No network fallback.

    Returns True on success, False on a recoverable per-item failure, or None
    if the file could not be found locally at all - callers must treat None
    as "ignore the whole question", not just this item.
    """
    if not src:
        return False

    media_name = extract_image_name(src)
    if not media_name:
        log_warning(f"Could not extract media name from src: {src}")
        return False

    media_path = find_image_file(question_id, media_name)
    if not media_path:
        log_warning(f"Media not found locally, ignoring question: {src}")
        return None

    output_path = build_output_path(category, os.path.basename(media_path))
    try:
        shutil.copy2(media_path, output_path)
    except Exception as error:
        log_error(f"Failed to copy media {media_path} to {output_path}: {error}")
        return False
    return True


NON_TRANSFORMABLE_CONTENT_TYPES = {"AUDIO", "VIDEO"}


def _is_non_image_media(entry: dict[str, Any]) -> bool:
    """True if entry's content_type is AUDIO/VIDEO (case-insensitive) and must skip image transform."""
    content_type = entry.get("content_type") or "IMAGE"
    if str(content_type).strip().upper() in NON_TRANSFORMABLE_CONTENT_TYPES:
        identifier = entry.get("key") or entry.get("src") or "<unknown>"
        print(f"Skipped because of AUDIO/VIDEO: {identifier}")
        return True
    return False


def process_resolution_output(resolution_result: dict[str, Any]) -> str | None:
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
    question_id = resolution_result.get("question_id")
    category = resolution_result.get("category")

    if not question_id or not category:
        log_error("Resolution result is missing question_id or category.")
        return None

    resolution = resolution_result.get("resolution") or {}

    for audit_entry in (resolution_result.get("image_audit") or []):
        src = audit_entry.get("src")
        target_width = audit_entry.get("max_width")
        target_height = audit_entry.get("max_height")

        if not src:
            continue

        if _is_non_image_media(audit_entry):
            continue

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

    question_images = resolution_result.get("question_images") or []
    option_images = resolution_result.get("option_images") or []

    has_question_images = bool(question_images)
    has_option_images = bool(option_images)

    if has_question_images and has_option_images:
        question_width = resolution.get("max_width")
        question_height = resolution.get("max_height")
        option_width = resolution.get("option_width")
        option_height = resolution.get("option_height")

        for image_entry in question_images:
            src = image_entry.get("src")
            if _is_non_image_media(image_entry):
                continue
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
                if _is_non_image_media(image_entry):
                    continue
                if transform_and_save(
                    question_id=question_id,
                    category=category,
                    src=image_entry.get("src"),
                    target_width=int(target_width),
                    target_height=int(target_height),
                ) is None:
                    return f"local media file not found: {image_entry.get('src')}"

    # Copy audio and video files without transformation
    for media_entry in (resolution_result.get("question_audios") or []):
        src = media_entry.get("src")
        if not src:
            continue
        if copy_media_and_save(question_id, category, src) is None:
            return f"local media file not found: {src}"

    for media_entry in (resolution_result.get("question_videos") or []):
        src = media_entry.get("src")
        if not src:
            continue
        if copy_media_and_save(question_id, category, src) is None:
            return f"local media file not found: {src}"

    return None
