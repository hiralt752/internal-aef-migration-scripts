import json
import re
from pathlib import Path


IMAGE_MAPPING_PATH = Path("config/image_mapping.json")
MEDIA_ROOT = Path("media")


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


SUBJECT_MAP = {
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
    "ELA": "ELA",
    "ISLAMIC": "Islamic",
    "SOCIAL": "Social"
}


ALL_SUBJECT_FOLDERS = [
    "Arabic",
    "Biology",
    "Chemistry",
    "English",
    "ELA",
    "Islamic",
    "Math",
    "Physics",
    "Science",
    "Social"
]


SUBJECT_FALLBACK_FOLDERS = {
    "Science": [
        "Science",
        "Biology",
        "Chemistry",
        "Physics"
    ],
    "Biology": [
        "Biology",
        "Science"
    ],
    "Chemistry": [
        "Chemistry",
        "Science"
    ],
    "Physics": [
        "Physics",
        "Science"
    ],
    "Math": [
        "Math"
    ],
    "Arabic": [
        "Arabic"
    ],
    "English": [
        "English",
        "ELA"
    ],
    "ELA": [
        "ELA",
        "English"
    ],
    "Islamic": [
        "Islamic"
    ],
    "Social": [
        "Social"
    ]
}


def load_image_mapping(project_root):
    mapping_file = Path(project_root) / IMAGE_MAPPING_PATH

    if not mapping_file.exists():
        print(
            f"[WARN] Image mapping not found: {mapping_file}",
            flush=True
        )
        return {}

    with open(
        mapping_file,
        "r",
        encoding="utf-8"
    ) as f:
        return json.load(f)


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

    return SUBJECT_MAP.get(
        subject.upper(),
        subject.title()
    )


def extract_url_from_image_obj(value):
    if not isinstance(value, dict):
        return None

    for key in URL_KEYS:
        if value.get(key):
            return str(
                value.get(key)
            ).strip()

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
                    url = extract_url_from_image_obj(
                        value
                    )

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
                            url = extract_url_from_image_obj(
                                item
                            )

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


def get_subject_search_order(subject_folder):
    """
    Example:
    If folder_subject is Science, image may physically exist under:
    media/Biology/IMAGE
    media/Chemistry/IMAGE
    media/Physics/IMAGE
    media/Science/IMAGE

    So we search Science family first, then all remaining subjects.
    """

    normalized_subject = normalize_subject_folder(
        subject_folder
    )

    priority_folders = SUBJECT_FALLBACK_FOLDERS.get(
        normalized_subject,
        []
    )

    search_order = []

    for folder in priority_folders:
        if folder not in search_order:
            search_order.append(folder)

    for folder in ALL_SUBJECT_FOLDERS:
        if folder not in search_order:
            search_order.append(folder)

    return search_order


def find_file_by_name_in_subjects(
    project_root,
    file_name,
    subject_folder=None
):
    media_root = Path(project_root) / MEDIA_ROOT

    if not media_root.exists():
        return None

    search_order = get_subject_search_order(
        subject_folder
    )

    for folder in search_order:
        possible_path = (
            media_root
            / folder
            / "IMAGE"
            / file_name
        )

        if possible_path.exists():
            return possible_path

    direct_image_path = (
        media_root
        / "IMAGE"
        / file_name
    )

    if direct_image_path.exists():
        return direct_image_path

    return None


def find_file_by_recursive_search(
    project_root,
    file_name
):
    media_root = Path(project_root) / MEDIA_ROOT

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
            "exists": False,
            "searched_subjects": get_subject_search_order(subject_folder)
        }

    subject_match = find_file_by_name_in_subjects(
        project_root=project_root,
        file_name=local_file_name,
        subject_folder=subject_folder
    )

    if subject_match:
        return {
            "status": "resolved_by_subject_search",
            "local_file_name": local_file_name,
            "local_path": str(subject_match),
            "exists": True,
            "searched_subjects": get_subject_search_order(subject_folder)
        }

    recursive_match = find_file_by_recursive_search(
        project_root=project_root,
        file_name=local_file_name
    )

    if recursive_match:
        return {
            "status": "resolved_by_recursive_search",
            "local_file_name": local_file_name,
            "local_path": str(recursive_match),
            "exists": True,
            "searched_subjects": get_subject_search_order(subject_folder)
        }

    fallback_path = None

    search_order = get_subject_search_order(
        subject_folder
    )

    if search_order:
        fallback_path = (
            Path(project_root)
            / MEDIA_ROOT
            / search_order[0]
            / "IMAGE"
            / local_file_name
        )

    return {
        "status": "local_file_not_found",
        "local_file_name": local_file_name,
        "local_path": str(fallback_path) if fallback_path else None,
        "exists": False,
        "searched_subjects": search_order
    }


def extract_images_from_question(
    question,
    image_mapping,
    project_root=None,
    subject=None
):
    if project_root is None:
        project_root = Path.cwd()

    question_id = get_question_id(
        question
    )

    subject_folder = normalize_subject_folder(
        subject
    )

    raw_images = find_images_recursively(
        question
    )

    images = []
    seen = set()

    for image_item in raw_images:
        image_url = image_item.get(
            "url"
        )

        dedupe_key = (
            image_item.get("location"),
            image_url
        )

        if dedupe_key in seen:
            continue

        seen.add(
            dedupe_key
        )

        resolved = resolve_local_image_path(
            project_root=project_root,
            question_id=question_id,
            image_url=image_url,
            subject_folder=subject_folder,
            image_mapping=image_mapping
        )

        images.append(
            {
                "location": image_item.get("location"),
                "url": image_url,
                "local_file_name": resolved.get("local_file_name"),
                "local_path": resolved.get("local_path"),
                "exists": resolved.get("exists"),
                "status": resolved.get("status"),
                "searched_subjects": resolved.get("searched_subjects", [])
            }
        )

    return images
