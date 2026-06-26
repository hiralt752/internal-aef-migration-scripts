from functools import lru_cache
from pathlib import Path
import json
import os
import re

from services.html_text_extractor import html_to_text
from services.json_utils import read_json_file


def _read_int_env(
    name,
    default
):
    try:
        return int(
            os.getenv(
                name,
                str(default)
            )
        )
    except Exception:
        return default


def _read_text_env(
    name,
    default
):
    value = os.getenv(
        name
    )

    if value is None:
        return default

    value = str(value).strip()
    return value or default


DEFAULT_MAX_SECTION_TEXTS = _read_int_env(
    "AI_ENGINE_LESSON_MAX_SECTION_TEXTS",
    40
)
DEFAULT_MAX_SECTION_CHARS = _read_int_env(
    "AI_ENGINE_LESSON_MAX_SECTION_CHARS",
    8000
)
DEFAULT_CONTEXT_MODE = _read_text_env(
    "AI_ENGINE_LESSON_CONTEXT_MODE",
    "filtered_text"
).lower()
UUID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE
)
VERSION_PATTERN = re.compile(
    r"^\d+(?:\.\d+){1,3}$"
)
ISO_TIMESTAMP_PATTERN = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}"
)
LAYOUT_PATTERN = re.compile(
    r"^(?:layout|theme|template)-[a-z0-9_-]+$",
    re.IGNORECASE
)
WIDGET_PATTERN = re.compile(
    r"^[A-Za-z][A-Za-z0-9]*Widget$"
)

SKIP_KEYS = {
    "id",
    "sectionid",
    "contentid",
    "slideid",
    "slidename",
    "itemtype",
    "type",
    "status",
    "version",
    "layout",
    "bglayout",
    "ratio",
    "corners",
    "animationtype",
    "name",
    "coordinates",
    "hotspotid",
    "showprogressbar",
    "disableprimarybutton",
    "isdefaultdisabled",
    "islastslide",
    "zoom",
    "loop",
    "autoplay",
    "haspassage",
    "submitlimit",
    "matchingtype",
    "shuffled",
    "mode",
    "numberofstars",
    "htmltype"
}

SKIP_VALUE_TOKENS = {
    "content",
    "published",
    "non_interactive",
    "interactive",
    "slide",
    "auto",
    "rounded-square",
    "walk"
}

SKIP_EXACT_TEXTS = {
    "english",
    "arabic",
    "correct.",
    "incorrect.",
    "select the correct answer:",
    "type the correct option."
}

PREFERRED_TEXT_KEYS = {
    "title",
    "text",
    "subtitle",
    "instructions",
    "instruction",
    "description",
    "prompt",
    "question",
    "explanation",
    "summary",
    "objectives",
    "objective",
    "passage",
    "statement",
    "label",
    "heading"
}


def _resolve_project_root(project_root=None):
    if project_root:
        return Path(project_root).resolve()

    return Path(__file__).resolve().parent.parent


def _is_probably_asset_reference(value):
    value = str(value or "").strip()

    if not value:
        return True

    lowered = value.lower()

    if lowered.startswith(("http://", "https://", "gs://", "file://")):
        return True

    if "/" in value or "\\" in value:
        suffix = Path(value).suffix.lower()

        if suffix in {
            ".png",
            ".jpg",
            ".jpeg",
            ".gif",
            ".webp",
            ".svg",
            ".mp3",
            ".wav",
            ".mp4",
            ".json",
            ".pdf"
        }:
            return True

    return False


def _normalize_text(value):
    return (
        str(value or "")
        .replace("\u200b", " ")
        .replace("\ufeff", " ")
        .strip()
    )


def _is_probably_noise_text(
    value,
    parent_key=None
):
    value = _normalize_text(value)

    if len(value) < 2:
        return False

    lowered = value.lower()

    if lowered in SKIP_VALUE_TOKENS:
        return True

    if lowered in SKIP_EXACT_TEXTS:
        return True

    if UUID_PATTERN.match(value):
        return True

    if VERSION_PATTERN.match(value):
        return True

    if ISO_TIMESTAMP_PATTERN.match(value):
        return True

    if WIDGET_PATTERN.match(value):
        return True

    if LAYOUT_PATTERN.match(lowered):
        return True

    if (
        "_" in value
        and value.upper() == value
        and len(value) <= 40
    ):
        return True

    normalized_parent = str(
        parent_key or ""
    ).strip().lower()

    if normalized_parent in SKIP_KEYS:
        return True

    return False


def _looks_like_meaningful_text(
    value,
    parent_key=None
):
    value = _normalize_text(value)
    normalized_parent = str(
        parent_key or ""
    ).strip().lower()

    if normalized_parent in PREFERRED_TEXT_KEYS:
        return True

    if len(value) >= 25:
        return True

    if len(value.split()) >= 3:
        return True

    return False


def _should_keep_text(
    value,
    parent_key=None
):
    value = _normalize_text(value)

    if len(value) < 2:
        return False

    if _is_probably_asset_reference(value):
        return False

    if _is_probably_noise_text(
        value,
        parent_key=parent_key
    ):
        return False

    return _looks_like_meaningful_text(
        value,
        parent_key=parent_key
    )


def _is_selected_key_mode(
    context_mode
):
    return str(
        context_mode or ""
    ).strip().lower() == "selected_keys_full_text"


def _collect_texts(
    value,
    texts,
    parent_key=None,
    context_mode=DEFAULT_CONTEXT_MODE
):
    normalized_parent = str(
        parent_key or ""
    ).strip().lower()
    selected_key_mode = _is_selected_key_mode(
        context_mode
    )

    if isinstance(value, dict):
        for key, item in value.items():
            normalized_key = str(key or "").strip().lower()

            if normalized_key in {
                "image",
                "audio",
                "video",
                "src",
                "url",
                "path",
                "filename",
                "icon"
            }:
                continue

            if normalized_key in SKIP_KEYS:
                continue

            _collect_texts(
                item,
                texts,
                parent_key=normalized_key,
                context_mode=context_mode
            )

        return

    if isinstance(value, list):
        for item in value:
            _collect_texts(
                item,
                texts,
                parent_key=parent_key,
                context_mode=context_mode
            )

        return

    if not isinstance(value, str):
        return

    clean_text = html_to_text(value)
    clean_text = _normalize_text(clean_text)

    if selected_key_mode:
        if normalized_parent not in PREFERRED_TEXT_KEYS:
            return

        if not clean_text:
            return

        texts.append(clean_text)
        return

    if not _should_keep_text(
        clean_text,
        parent_key=parent_key
    ):
        return

    texts.append(clean_text)


def _dedupe_preserve_order(values):
    seen = set()
    result = []

    for value in values:
        normalized = str(value).strip()

        if not normalized or normalized in seen:
            continue

        seen.add(normalized)
        result.append(normalized)

    return result


@lru_cache(maxsize=1)
def load_question_lo_map(project_root=None):
    root = _resolve_project_root(project_root)
    filtered_questions_path = (
        root
        /
        "config"
        /
        "filtered_questions.json"
    )

    data = read_json_file(filtered_questions_path, default=[])
    question_lo_map = {}

    if not isinstance(data, list):
        return question_lo_map

    for entry in data:
        if not isinstance(entry, dict):
            continue

        lo_id = str(entry.get("lo_id") or "").strip()

        if not lo_id:
            continue

        for question_id in entry.get("question_ids") or []:
            normalized_question_id = str(question_id or "").strip()

            if not normalized_question_id:
                continue

            question_lo_map[normalized_question_id] = lo_id

    return question_lo_map


def get_lo_id_for_question(
    question_id,
    project_root=None,
    question_lo_map=None
):
    normalized_question_id = str(question_id or "").strip()

    if not normalized_question_id:
        return None

    mapping = question_lo_map or load_question_lo_map(project_root)
    return mapping.get(normalized_question_id)


def has_lo_id_mapping(
    question_id,
    project_root=None,
    question_lo_map=None
):
    return get_lo_id_for_question(
        question_id=question_id,
        project_root=project_root,
        question_lo_map=question_lo_map
    ) is not None


def get_record_lo_id(
    record,
    project_root=None,
    question_lo_map=None
):
    question_id = str(
        record.get("question_id")
        or record.get("id")
        or (
            record.get("normalized_input", {})
            if isinstance(record.get("normalized_input"), dict)
            else {}
        ).get("question_id")
        or ""
    ).strip()

    return get_lo_id_for_question(
        question_id=question_id,
        project_root=project_root,
        question_lo_map=question_lo_map
    )


def _build_section_payload(
    json_file,
    lo_id,
    context_mode=DEFAULT_CONTEXT_MODE,
    max_texts=DEFAULT_MAX_SECTION_TEXTS,
    max_chars=DEFAULT_MAX_SECTION_CHARS
):
    payload = read_json_file(json_file, default={})

    if not isinstance(payload, (dict, list)):
        return None

    relative_parts = list(
        json_file.relative_to(json_file.parents[1]).parts
    )
    section_name = (
        relative_parts[-2]
        if len(relative_parts) >= 2
        else json_file.parent.name
    )

    normalized_mode = str(
        context_mode or DEFAULT_CONTEXT_MODE
    ).strip().lower()

    if normalized_mode == "raw_json":
        raw_text = json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            default=str
        )

        return {
            "lo_id": lo_id,
            "section_name": section_name,
            "file_path": str(json_file),
            "mode": "raw_json",
            "texts": [raw_text]
        }

    texts = []
    _collect_texts(
        payload,
        texts,
        context_mode=normalized_mode
    )

    if not _is_selected_key_mode(
        normalized_mode
    ):
        texts = _dedupe_preserve_order(texts)

    if not texts:
        return None

    unlimited = (
        int(max_texts or 0) == 0
        and int(max_chars or 0) == 0
    )

    limited_texts = []
    char_count = 0

    text_iterable = (
        texts
        if unlimited or int(max_texts or 0) <= 0
        else texts[:max_texts]
    )

    for text in text_iterable:
        if (
            not unlimited
            and int(max_chars or 0) > 0
            and char_count >= max_chars
        ):
            break

        if unlimited or int(max_chars or 0) <= 0:
            clipped = text.strip()
        else:
            remaining = max_chars - char_count
            clipped = text[:remaining].strip()

        if not clipped:
            continue

        limited_texts.append(clipped)
        char_count += len(clipped)

    if not limited_texts:
        return None

    return {
        "lo_id": lo_id,
        "section_name": section_name,
        "file_path": str(json_file),
        "mode": "filtered_text",
        "texts": limited_texts
    }


@lru_cache(maxsize=4096)
def load_lesson_context(
    lo_id,
    project_root=None,
    context_mode=DEFAULT_CONTEXT_MODE,
    max_texts=DEFAULT_MAX_SECTION_TEXTS,
    max_chars=DEFAULT_MAX_SECTION_CHARS
):
    normalized_lo_id = str(lo_id or "").strip()
    normalized_mode = str(
        context_mode or DEFAULT_CONTEXT_MODE
    ).strip().lower()

    if not normalized_lo_id:
        return {
            "lo_id": None,
            "available": False,
            "context_mode": normalized_mode,
            "lesson_dir": None,
            "json_files": [],
            "sections": []
        }

    root = _resolve_project_root(project_root)
    lesson_dir = root / "LessonContentData" / normalized_lo_id

    if not lesson_dir.exists():
        return {
            "lo_id": normalized_lo_id,
            "available": False,
            "context_mode": normalized_mode,
            "lesson_dir": str(lesson_dir),
            "json_files": [],
            "sections": []
        }

    json_files = sorted(
        lesson_dir.rglob("*.json")
    )
    sections = []

    for json_file in json_files:
        section_payload = _build_section_payload(
            json_file=json_file,
            lo_id=normalized_lo_id,
            context_mode=normalized_mode,
            max_texts=max_texts,
            max_chars=max_chars
        )

        if section_payload:
            sections.append(section_payload)

    return {
        "lo_id": normalized_lo_id,
        "available": len(sections) > 0,
        "context_mode": normalized_mode,
        "lesson_dir": str(lesson_dir),
        "json_files": [str(item) for item in json_files],
        "sections": sections
    }


def build_lesson_context_text(lesson_context):
    if not isinstance(lesson_context, dict):
        return ""

    if not lesson_context.get("available"):
        return ""

    lo_id = lesson_context.get("lo_id")
    lines = [
        f"LESSON CONTENT FOR LO_ID {lo_id}"
    ]

    for section in lesson_context.get("sections", []):
        section_name = section.get("section_name") or "Lesson Section"
        lines.append(f"SECTION: {section_name}")

        for text in section.get("texts", []):
            lines.append(f"- {text}")

    lines.append(f"END LESSON CONTENT {lo_id}")
    return "\n".join(lines)
