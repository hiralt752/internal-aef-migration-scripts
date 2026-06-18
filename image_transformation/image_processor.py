"""
Locate and transform images using image_resolution_engine output.
"""

import fnmatch
import os
import urllib.request
from typing import Any

from image_transformation.image_transformation import (
    log_error,
    log_info,
    log_warning,
    transform_image,
)

SCRIPTS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MEDIA_ROOT = os.path.normpath(os.path.join(SCRIPTS_DIR, "..", "..", "media"))
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


def find_image_file(question_id: str, image_name: str, category: str) -> str | None:
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
    processed_sources: set[str],
) -> bool:
    """Locate one image, transform it, and save the result."""
    if not src:
        return False

    if src in processed_sources:
        log_info(f"Skipping already processed image: {src}")
        return False

    image_name = extract_image_name(src)
    if not image_name:
        log_warning(f"Could not extract image name from src: {src}")
        return False

    search_pattern = f"{question_id}*{image_name}"
    log_info(f"Searching image: {search_pattern}")

    image_path = find_image_file(question_id, image_name, category)
    if not image_path:
        log_warning(f"Image not found locally for pattern: {search_pattern}. Attempting download...")
        
        clean_src = src.replace('../', '')
        if clean_src.startswith('./'):
            clean_src = clean_src[2:]
        url = f"https://shared.alefed.com/{clean_src}"
        
        env_file = os.path.join(SCRIPTS_DIR, ".env")
        cookie_val = ""
        if os.path.isfile(env_file):
            with open(env_file, "r", encoding="utf-8") as f:
                for line in f:
                    if line.startswith("YOUR_ASSETS_COOKIE="):
                        cookie_val = line.strip().split("=", 1)[1].strip('"\'')
        
        download_dir = os.path.join(SCRIPTS_DIR, "downloaded_images", category)
        os.makedirs(download_dir, exist_ok=True)
        download_path = os.path.join(download_dir, f"{question_id}_{image_name}")
        
        req = urllib.request.Request(url)
        req.add_header('accept', 'image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8')
        req.add_header('cache-control', 'no-cache')
        if cookie_val:
            req.add_header('cookie', cookie_val)
        
        try:
            with urllib.request.urlopen(req) as response:
                with open(download_path, "wb") as out_file:
                    out_file.write(response.read())
            log_info(f"Downloaded image successfully from {url}")
            image_path = download_path
        except Exception as e:
            log_error(f"Failed to download image {url}: {e}")
            return False

    log_info("Image ready for transformation.")
    log_info(f"Applying resolution {target_width}x{target_height}")

    output_path = build_output_path(category, os.path.basename(image_path))

    try:
        transform_image(image_path, output_path, target_width, target_height)
    except Exception as error:
        log_error(f"Image transformation failed: {error}")
        return False

    processed_sources.add(src)
    log_info("Image transformation completed.")
    log_info(f"Saved transformed image: {output_path}")
    return True


def process_resolution_output(resolution_result: dict[str, Any]) -> None:
    """
    Process all images described in one image_resolution_engine result.

    Priority:
    1. image_audit (uses per-record max_width / max_height)
    2. question_images
    3. option_images
    """
    question_id = resolution_result.get("question_id")
    category = resolution_result.get("category")

    if not question_id or not category:
        log_error("Resolution result is missing question_id or category.")
        return

    log_info(f"Processing question: {question_id}")
    log_info(f"Category: {category}")

    resolution = resolution_result.get("resolution") or {}
    processed_sources: set[str] = set()

    image_audit = resolution_result.get("image_audit") or []
    if image_audit:
        log_info(f"Processing {len(image_audit)} image(s) from image_audit.")

        for audit_entry in image_audit:
            src = audit_entry.get("src")
            target_width = audit_entry.get("max_width")
            target_height = audit_entry.get("max_height")

            if not src:
                continue

            if target_width is None or target_height is None:
                log_warning(
                    f"Skipping audit image with missing dimensions: {src}"
                )
                continue

            transform_and_save(
                question_id=question_id,
                category=category,
                src=src,
                target_width=int(target_width),
                target_height=int(target_height),
                processed_sources=processed_sources,
            )

    question_images = resolution_result.get("question_images") or []
    option_images = resolution_result.get("option_images") or []

    if question_images:
        log_info(f"Processing {len(question_images)} question image(s).")

    if option_images:
        log_info(f"Processing {len(option_images)} option image(s).")

    has_question_images = bool(question_images)
    has_option_images = bool(option_images)

    if has_question_images and has_option_images:
        question_width = resolution.get("max_width")
        question_height = resolution.get("max_height")
        option_width = resolution.get("option_width")
        option_height = resolution.get("option_height")

        for image_entry in question_images:
            src = image_entry.get("src")
            if question_width is None or question_height is None:
                log_warning(f"Skipping question image with missing resolution: {src}")
                continue

            transform_and_save(
                question_id=question_id,
                category=category,
                src=src,
                target_width=int(question_width),
                target_height=int(question_height),
                processed_sources=processed_sources,
            )

        for image_entry in option_images:
            src = image_entry.get("src")
            if option_width is None or option_height is None:
                log_warning(f"Skipping option image with missing resolution: {src}")
                continue

            transform_and_save(
                question_id=question_id,
                category=category,
                src=src,
                target_width=int(option_width),
                target_height=int(option_height),
                processed_sources=processed_sources,
            )

    elif has_question_images or has_option_images:
        target_width = resolution.get("max_width")
        target_height = resolution.get("max_height")

        if target_width is None or target_height is None:
            log_warning("Skipping images because resolution max_width/max_height is missing.")
        else:
            for image_entry in question_images + option_images:
                transform_and_save(
                    question_id=question_id,
                    category=category,
                    src=image_entry.get("src"),
                    target_width=int(target_width),
                    target_height=int(target_height),
                    processed_sources=processed_sources,
                )

    log_info("Question completed.")
