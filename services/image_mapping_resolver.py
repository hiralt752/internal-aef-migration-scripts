import json
import re
from pathlib import Path
from datetime import datetime


IMAGE_MAPPING_PATH = Path("config/image_mapping.json")
MEDIA_ROOT = Path("media")
REPORT_ROOT = Path("reports")
IMAGE_REPORT_DIR = REPORT_ROOT / "image_extraction"


IMAGE_KEYS = {
    "image",
    "images",
    "stemImage",
    "stemVideo",
    "sideImage",
    "fibImage",
    "backgroundImage",
    "audio",
    "video"
}


URL_KEYS = {
    "url",
    "src",
    "source",
    "path"
}


HTML_IMAGE_SRC_PATTERN = re.compile(
    r"""<img[^>]+src=["']([^"']+)["']""",
    re.IGNORECASE
)


def load_json_file(file_path):
    file_path = Path(file_path)

    if not file_path.exists():
        return {}

    with open(
        file_path,
        "r",
        encoding="utf-8"
    ) as f:
        return json.load(f)


def ensure_dir(path):
    Path(path).mkdir(
        parents=True,
        exist_ok=True
    )


def get_question_id(question):
    return (
        question
        .get("metadata", {})
        .get("general", {})
        .get("externalId")
    )


def normalize_subject_folder(subject):
    if not subject:
        return None

    subject = str(subject).strip()

    subject_map = {
        "MATH": "Math",
        "MATH_EN": "Math",
        "SCIENCE": "Science",
        "SCIENCE_EN": "Science",
        "BIOLOGY": "Biology",
        "BIOLOGY_EN": "Biology",
        "CHEMISTRY": "Chemistry",
        "CHEMISTRY_EN": "Chemistry",
        "PHYSICS": "Physics",
        "PHYSICS_EN": "Physics",
        "ARABIC": "Arabic",
        "ENGLISH": "English",
        "ELA": "English",
        "ISLAMIC": "Islamic",
        "SOCIAL": "Social"
    }

    return subject_map.get(
        subject.upper(),
        subject.title()
    )


def extract_url_from_image_obj(value):
    if not isinstance(value, dict):
        return None

    for key in URL_KEYS:
        if value.get(key):
            return str(value.get(key)).strip()

    return None


def find_images_recursively(
    obj,
    current_path="root"
):
    found_images = []

    if isinstance(obj, dict):
        for key, value in obj.items():
            next_path = f"{current_path}.{key}"

            if key in IMAGE_KEYS:
                if isinstance(value, dict):
                    url = extract_url_from_image_obj(value)

                    if url:
                        found_images.append(
                            {
                                "location": next_path,
                                "url": url,
                                "raw": value
                            }
                        )

                elif isinstance(value, list):
                    for index, item in enumerate(value):
                        item_path = f"{next_path}[{index}]"

                        if isinstance(item, dict):
                            url = extract_url_from_image_obj(item)

                            if url:
                                found_images.append(
                                    {
                                        "location": item_path,
                                        "url": url,
                                        "raw": item
                                    }
                                )

                            found_images.extend(
                                find_images_recursively(
                                    item,
                                    item_path
                                )
                            )

            found_images.extend(
                find_images_recursively(
                    value,
                    next_path
                )
            )

    elif isinstance(obj, list):
        for index, item in enumerate(obj):
            found_images.extend(
                find_images_recursively(
                    item,
                    f"{current_path}[{index}]"
                )
            )

    elif isinstance(obj, str):
        for index, match in enumerate(
            HTML_IMAGE_SRC_PATTERN.finditer(obj),
            start=1
        ):
            url = str(
                match.group(1) or ""
            ).strip()

            if not url:
                continue

            found_images.append(
                {
                    "location": f"{current_path}.html_img[{index}]",
                    "url": url,
                    "raw": {
                        "src": url
                    }
                }
            )

    return found_images


def find_file_by_name(
    project_root,
    file_name
):
    media_root = project_root / MEDIA_ROOT

    if not media_root.exists():
        return None

    matches = list(
        media_root.rglob(file_name)
    )

    if not matches:
        return None

    return matches[0]


def resolve_local_image_path(
    project_root,
    question_id,
    image_url,
    subject_folder,
    image_mapping
):
    question_map = image_mapping.get(
        question_id,
        {}
    )

    local_file_name = question_map.get(
        image_url
    )

    if not local_file_name:
        return {
            "status": "mapping_not_found",
            "local_file_name": None,
            "local_path": None,
            "exists": False
        }

    possible_paths = []

    if subject_folder:
        possible_paths.append(
            project_root
            / MEDIA_ROOT
            / subject_folder
            / "IMAGE"
            / local_file_name
        )

    possible_paths.append(
        project_root
        / MEDIA_ROOT
        / "IMAGE"
        / local_file_name
    )

    for possible_path in possible_paths:
        if possible_path.exists():
            return {
                "status": "resolved",
                "local_file_name": local_file_name,
                "local_path": str(possible_path),
                "exists": True
            }

    fallback_path = find_file_by_name(
        project_root,
        local_file_name
    )

    if fallback_path:
        return {
            "status": "resolved_by_recursive_search",
            "local_file_name": local_file_name,
            "local_path": str(fallback_path),
            "exists": True
        }

    return {
        "status": "local_file_not_found",
        "local_file_name": local_file_name,
        "local_path": str(possible_paths[0]) if possible_paths else None,
        "exists": False
    }


def build_image_report_payload(
    question_id,
    subject,
    question_type,
    resolved_images,
    missing_mappings,
    missing_files
):
    return {
        "question_id": question_id,
        "subject": subject,
        "question_type": question_type,
        "total_images_found": len(resolved_images),
        "resolved_count": len(
            [
                image
                for image in resolved_images
                if image.get("exists")
            ]
        ),
        "missing_mapping_count": len(missing_mappings),
        "missing_file_count": len(missing_files),
        "resolved_images": resolved_images,
        "missing_mappings": missing_mappings,
        "missing_files": missing_files
    }


def append_jsonl(
    file_path,
    payload
):
    ensure_dir(
        Path(file_path).parent
    )

    with open(
        file_path,
        "a",
        encoding="utf-8"
    ) as f:
        f.write(
            json.dumps(
                payload,
                ensure_ascii=False
            )
            + "\n"
        )


def resolve_images_for_question(
    question,
    subject=None,
    project_root=None,
    image_mapping=None,
    write_report=True
):
    if project_root is None:
        project_root = Path.cwd()

    project_root = Path(project_root)

    if image_mapping is None:
        image_mapping = load_json_file(
            project_root / IMAGE_MAPPING_PATH
        )

    question_id = get_question_id(
        question
    )

    question_type = question.get(
        "type"
    )

    subject_folder = normalize_subject_folder(
        subject
    )

    raw_images = find_images_recursively(
        question
    )

    resolved_images = []
    missing_mappings = []
    missing_files = []

    for image_item in raw_images:
        image_url = image_item.get(
            "url"
        )

        resolved = resolve_local_image_path(
            project_root=project_root,
            question_id=question_id,
            image_url=image_url,
            subject_folder=subject_folder,
            image_mapping=image_mapping
        )

        image_payload = {
            "location": image_item.get("location"),
            "url": image_url,
            "local_file_name": resolved.get("local_file_name"),
            "local_path": resolved.get("local_path"),
            "exists": resolved.get("exists"),
            "status": resolved.get("status")
        }

        resolved_images.append(
            image_payload
        )

        if resolved.get("status") == "mapping_not_found":
            missing_mappings.append(
                image_payload
            )

        elif resolved.get("status") == "local_file_not_found":
            missing_files.append(
                image_payload
            )

    report_payload = build_image_report_payload(
        question_id=question_id,
        subject=subject,
        question_type=question_type,
        resolved_images=resolved_images,
        missing_mappings=missing_mappings,
        missing_files=missing_files
    )

    if write_report:
        timestamp = datetime.now().strftime(
            "%Y%m%d"
        )

        append_jsonl(
            project_root
            / IMAGE_REPORT_DIR
            / f"image_extraction_report_{timestamp}.jsonl",
            report_payload
        )

        if missing_mappings:
            append_jsonl(
                project_root
                / IMAGE_REPORT_DIR
                / f"missing_image_mapping_{timestamp}.jsonl",
                report_payload
            )

        if missing_files:
            append_jsonl(
                project_root
                / IMAGE_REPORT_DIR
                / f"missing_local_image_file_{timestamp}.jsonl",
                report_payload
            )

    return {
        "images": resolved_images,
        "report": report_payload
    }
