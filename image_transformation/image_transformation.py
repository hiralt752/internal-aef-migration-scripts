"""
Image transformation module.

Resize images proportionally with padding to target dimensions.
"""

import os

from PIL import Image, ImageFile
ImageFile.LOAD_TRUNCATED_IMAGES = True

PADDING_COLOR = (255, 255, 255)


def log_info(message: str) -> None:
    print(f"[INFO] {message}")


def log_warning(message: str) -> None:
    print(f"[WARNING] {message}")


def log_error(message: str) -> None:
    print(f"[ERROR] {message}")


def transform_image(
    image_path: str,
    output_path: str,
    target_width: int,
    target_height: int,
) -> None:
    """
    Resize image proportionally, add padding,
    without stamping the target dimensions.
    """
    with Image.open(image_path) as img:
        img = img.convert("RGB")

        original_width, original_height = img.size

        scale = min(
            target_width / original_width,
            target_height / original_height,
        )

        new_width = int(original_width * scale)
        new_height = int(original_height * scale)

        resized = img.resize((new_width, new_height), Image.LANCZOS)

        canvas = Image.new(
            "RGB",
            (target_width, target_height),
            PADDING_COLOR,
        )

        x_offset = (target_width - new_width) // 2
        y_offset = (target_height - new_height) // 2

        canvas.paste(resized, (x_offset, y_offset))

        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        canvas.save(output_path, quality=95)
