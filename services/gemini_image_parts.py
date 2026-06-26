import mimetypes
from pathlib import Path

from google.genai import types


SUPPORTED_IMAGE_MIME_TYPES = {
    "image/png",
    "image/jpeg",
    "image/webp",
    "image/heic",
    "image/heif"
}


def get_mime_type(file_path):
    mime_type, _ = mimetypes.guess_type(
        str(file_path)
    )

    return mime_type or "image/png"


def build_image_parts(images):
    parts = []
    skipped = []

    for image in images:
        local_path = image.get(
            "local_path"
        )

        if not local_path:
            skipped.append(
                {
                    "reason": "missing_local_path",
                    "image": image
                }
            )
            continue

        path = Path(local_path)

        if not path.exists():
            skipped.append(
                {
                    "reason": "local_file_not_found",
                    "local_path": local_path,
                    "image": image
                }
            )
            continue

        mime_type = get_mime_type(
            path
        )

        if mime_type not in SUPPORTED_IMAGE_MIME_TYPES:
            skipped.append(
                {
                    "reason": "unsupported_mime_type",
                    "mime_type": mime_type,
                    "local_path": local_path,
                    "image": image
                }
            )
            continue

        try:
            with open(
                path,
                "rb"
            ) as f:
                image_bytes = f.read()

            parts.append(
                types.Part.from_bytes(
                    data=image_bytes,
                    mime_type=mime_type
                )
            )

        except Exception as e:
            skipped.append(
                {
                    "reason": "image_read_failed",
                    "error": str(e),
                    "local_path": local_path,
                    "image": image
                }
            )

    return parts, skipped