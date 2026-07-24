import re
from bs4 import BeautifulSoup
from copy import deepcopy

from builders.metadata_builder import build_metadata
from helpers.span_remover import remove_span_texts_from_html

SCHEMA_VERSION = {"major": 1, "minor": 0, "patch": 0}
LIFECYCLE_STATUS = "DRAFT"
HARDCODE = {
    "version": "1.0",
    "optionsStyle": "option-style-1",
    "dropLimit": 1,
    "optionsPosition": "bottom",
    "maxAttempts": 1,
    "scoring": {
        "normalizedMin": 0,
        "normalizedMax": 1,
        "defaultNormalizedValue": 0,
    },
    "shouldAutoGraded": True,
    "matchMode": "ALL",
}


def _extract_audio(html):
    soup = BeautifulSoup(html, "html.parser")
    audio_tag = soup.find("audio")
    if audio_tag:
        url = audio_tag.get("src", "")
        audio_tag.decompose()
        return str(soup), {"url": url} if url else None
    return html, None


def _extract_video(html):
    soup = BeautifulSoup(html, "html.parser")
    video_tag = soup.find("video")
    if video_tag:
        url = video_tag.get("src", "")
        video_tag.decompose()
        return str(soup), {"url": url} if url else None
    return html, None


def replace_blank_fields(html):
    if not html:
        return ""

    soup = BeautifulSoup(html, "html.parser")
    for blank in soup.find_all("blank-field"):
        blank.replace_with("@_@")
    return str(soup)


def html_to_text(html):
    if not html:
        return ""

    soup = BeautifulSoup(html, "html.parser")
    return soup.get_text(" ", strip=True)


def normalize_weight(weight):
    try:
        return round(float(weight) / 100, 4)
    except Exception:
        return 1.0


def _parse_option_content(value):
    if not value or not value.strip():
        return [{"type": "text", "text": ""}]
    soup = BeautifulSoup(value, "html.parser")
    img = soup.find("img")
    if img:
        url = img.get("src", "")
        img.decompose()
        text = soup.get_text(separator=" ").strip()
        items = []
        if url:
            items.append({"type": "image", "image": {"url": url}})
        if text:
            items.append({"type": "text", "text": text})
        return items if items else [{"type": "text", "text": ""}]
    text = soup.get_text(separator=" ").strip()
    if "<" not in value:
        text = value.strip()
    return [{"type": "text", "text": text}]


def _build_metadata(resp, legacy_status=LIFECYCLE_STATUS):
    meta = resp.get("metadata", {})
    outcomes = meta.get("curriculumOutcomes", []) or []
    first = outcomes[0] if outcomes else {}

    keywords = list(meta.get("keywords") or [])
    if meta.get("skillId"):
        keywords.append(str(meta["skillId"]))
    if meta.get("subSkill"):
        keywords.append(str(meta["subSkill"]))

    source = "AAT"

    sub_domain = []
    if meta.get("domains"):
        if isinstance(meta["domains"], list):
            sub_domain.extend(meta["domains"])
        else:
            sub_domain.append(str(meta["domains"]))
    if meta.get("subSkill"):
        sub_domain.append(str(meta["subSkill"]))

    tags = {"migration:source": "AAT"}
    if resp.get("createdAt"):
        tags["migration:originalCreatedAt"] = resp["createdAt"]
    if meta.get("authoredDate"):
        tags["migration:authoredDate"] = meta["authoredDate"]

    return {
        "general": {
            "code": resp.get("code"),
            "externalId": resp.get("id"),
            "title": None,
            "language": resp.get("language"),
            "keywords": keywords,
            "parentReference": None,
            "source": source,
        },
        "lifecycle": {"status": legacy_status},
        "technical": {"penAndPaper": meta.get("penAndPaper", False)},
        "educational": {
            "resourceType": meta.get("resourceType"),
            "difficultyLevel": meta.get("difficultyLevel"),
            "cognitiveDimensions": meta.get("cognitiveDimensions") or [],
            "knowledgeDimensions": meta.get("knowledgeDimensions") or [],
            "summativeAssessment": meta.get("summativeAssessment", False),
            "cefrLevel": meta.get("cefrLevel"),
            "proficiency": meta.get("proficiency"),
            "lexileLevel": meta.get("lexileLevel"),
            "logitValue": meta.get("logitValue"),
        },
        "rights": {"copyrights": meta.get("copyrights") or []},
        "classification": {
            "grade": first.get("grade"),
            "subject": first.get("subject"),
            "curriculum": first.get("curriculum"),
            "curriculumOutcomes": outcomes,
            "subDomain": sub_domain,
        },
        "annotation": {"tags": tags},
    }


def _process_dnd_prompt(prompt, question_id=None, lesson=None, file_path=None):
    if not prompt or not prompt.strip():
        return None, None, None, None
    prompt = remove_span_texts_from_html(prompt, question_id, lesson, file_path)
    prompt, audio = _extract_audio(prompt)
    prompt, video = _extract_video(prompt)
    cleaned = re.sub(
        r'<blank-field[^>]*>\s*</blank-field>',
        "@_@",
        prompt,
        flags=re.IGNORECASE | re.DOTALL,
    )
    soup = BeautifulSoup(cleaned, "html.parser")
    
    # Clean up disallowed tags in a single pass
    for tag in soup.find_all(["div", "colgroup", "col", "audio", "video", "a", "pre"]):
        if not tag.parent:
            continue
        if tag.name in ["colgroup", "col", "audio", "video"]:
            tag.decompose()
        elif tag.get("id") == "gtx-trans" or "gtx-trans-icon" in tag.get("class", []):
            tag.decompose()
        else:
            tag.unwrap()
        
    img = soup.find("img")
    side_image = None
    if img:
        src = img.get("src")
        img.decompose()
        if src:
            side_image = {"url": src}
    cleaned = str(soup).strip()
    return cleaned, audio, video, side_image


def _build_dnd_targets(blanks):
    return [
        {
            "id": idx + 1,
            "weight": round(b.get("weight", 100.0) / 100, 6),
            "swappable": False,
            "swapGroupId": 0,
            "position": None,
        }
        for idx, b in enumerate(blanks)
    ]


def _build_image_labelling_targets(blanks):
    return [
        {
            "id": idx + 1,
            "weight": round(b.get("weight", 100.0) / 100, 6),
            "swappable": False,
            "swapGroupId": 0,
            "position": b.get("position"),
        }
        for idx, b in enumerate(blanks)
    ]


def _build_dnd_options(choice_items):
    return [
        {
            "id": idx + 1,
            "content": _parse_option_content(item.get("value", "")),
        }
        for idx, item in enumerate(choice_items)
    ]


def _build_dnd_correct_answers(answer_mapping, blanks, choice_items):
    blank_id_to_pos = {b["id"]: i for i, b in enumerate(blanks)}
    choice_id_to_pos = {c["id"]: i for i, c in enumerate(choice_items)}

    choice_alternates = {}
    for item in choice_items:
        cid = item["id"]
        alts = set(item.get("alternateChoiceIds") or [])
        alts.add(cid)
        choice_alternates[cid] = alts

    correct_answers = []
    for mapping in answer_mapping:
        blank_id = mapping["blankId"]
        choice_id = mapping["choiceId"]

        blank_pos = blank_id_to_pos.get(blank_id)
        choice_pos = choice_id_to_pos.get(choice_id)

        if blank_pos is None:
            raise ValueError(f"blankId {blank_id} not found in body.blanks")
        if choice_pos is None:
            raise ValueError(f"choiceId {choice_id} not found in body.choices.choiceItems")

        target_id = blank_pos + 1
        acceptable_choice_ids = choice_alternates.get(choice_id, {choice_id})
        option_ids = sorted([
            choice_id_to_pos[cid] + 1
            for cid in acceptable_choice_ids
            if cid in choice_id_to_pos
        ])
        match_mode = "ANY" if len(option_ids) > 1 else "ALL"

        correct_answers.append({
            "targetId": target_id,
            "optionIds": option_ids,
            "matchMode": match_mode,
        })

    return correct_answers


def _build_modal_feedback(body):
    hints = [h for h in (body.get("hints") or []) if h and h.strip()]
    passage = body.get("passage")
    if not hints and not passage:
        return None
    mf = {}
    if hints:
        mf["hints"] = hints
    if passage:
        mf["passageId"] = passage
    return mf


def _build_background_image(bg):
    if not bg or not bg.get("src"):
        return None
    return {
        "url": bg["src"],
        "width": bg.get("width"),
        "height": bg.get("height"),
    }


def migrate_fill_in_blank_drag_drop(resp, status, question_id=None, lesson=None, file_path=None):
    body = resp.get("body", {})
    validation = resp.get("validation", {})
    valid_resp = validation.get("validResponse", {})
    choices = body.get("choices", {})
    choice_items = choices.get("choiceItems", [])
    blanks = body.get("blanks", [])
    prompt = body.get("prompt", "")

    sentence_text, audio, video, side_image = _process_dnd_prompt(prompt, question_id, lesson, file_path)
    targets = _build_dnd_targets(blanks)
    options = _build_dnd_options(choice_items)
    correct = _build_dnd_correct_answers(valid_resp.get("answerMapping", []), blanks, choice_items)
    modal_fb = _build_modal_feedback(body)

    outcome = {
        "scoringType": validation.get("scoringType", "EXACT_MATCH"),
        "scoring": deepcopy(HARDCODE["scoring"]),
        "validResponse": {
            "shouldAutoGraded": HARDCODE["shouldAutoGraded"],
            "correctAnswers": correct,
        },
    }

    item_body = {
        "version": HARDCODE["version"],
        "title": None,
        "subTitle": None,
        "instruction": None,
        "audio": audio,
        "video": video,
        "image": None,
        "backgroundLayout": None,
        "timeSpentConfig": None,
        "splitContent": None,
        "sideImage": side_image,
        "showDragHandle": choices.get("showDragHandle", True),
        "shuffled": choices.get("shuffle", True),
        "optionsStyle": HARDCODE["optionsStyle"],
        "dropLimit": HARDCODE["dropLimit"],
        "optionsPosition": HARDCODE["optionsPosition"],
        "statement": None,
        "sentence": {"text": sentence_text} if sentence_text else None,
        "targets": targets,
        "options": options,
    }

    doc = {
        "schemaVersion": deepcopy(SCHEMA_VERSION),
        "type": "DND",
        "subType": "BLANK_ON_QUESTION",
        "metadata": _build_metadata(resp, status),
        "itemBody": item_body,
        "responseDeclaration": {"maxAttempts": HARDCODE["maxAttempts"]},
        "outcomeDeclaration": outcome,
    }
    if modal_fb:
        doc["modalFeedback"] = modal_fb
    return doc


def migrate_image_labelling(resp, status, question_id=None, lesson=None, file_path=None):
    body = resp.get("body", {})
    validation = resp.get("validation", {})
    valid_resp = validation.get("validResponse", {})
    choices = body.get("choices", {})
    choice_items = choices.get("choiceItems", [])
    blanks = body.get("blanks", [])

    bg_image = _build_background_image(body.get("backgroundImage"))
    targets = _build_image_labelling_targets(blanks)
    options = _build_dnd_options(choice_items)
    correct = _build_dnd_correct_answers(valid_resp.get("answerMapping", []), blanks, choice_items)

    prompt = body.get("prompt", "")
    _, audio, video, side_image = (
        _process_dnd_prompt(prompt, question_id, lesson, file_path)
        if prompt
        else (None, None, None, None)
    )
    modal_fb = _build_modal_feedback(body)

    outcome = {
        "scoringType": validation.get("scoringType", "EXACT_MATCH"),
        "scoring": deepcopy(HARDCODE["scoring"]),
        "validResponse": {
            "shouldAutoGraded": HARDCODE["shouldAutoGraded"],
            "correctAnswers": correct,
        },
    }

    item_body = {
        "version": HARDCODE["version"],
        "title": None,
        "subTitle": None,
        "instruction": None,
        "audio": audio,
        "video": video,
        "image": None,
        "backgroundImage": bg_image,
        "backgroundLayout": None,
        "timeSpentConfig": None,
        "splitContent": None,
        "sideImage": side_image,
        "showDragHandle": choices.get("showDragHandle", True),
        "shuffled": choices.get("shuffle", True),
        "optionsStyle": HARDCODE["optionsStyle"],
        "dropLimit": HARDCODE["dropLimit"],
        "optionsPosition": HARDCODE["optionsPosition"],
        "statement": None,
        "sentence": None,
        "targets": targets,
        "options": options,
    }

    doc = {
        "schemaVersion": deepcopy(SCHEMA_VERSION),
        "type": "DND",
        "subType": "BLANK_ON_QUESTION",
        "metadata": _build_metadata(resp, status),
        "itemBody": item_body,
        "responseDeclaration": {"maxAttempts": HARDCODE["maxAttempts"]},
        "outcomeDeclaration": outcome,
    }
    if modal_fb:
        doc["modalFeedback"] = modal_fb
    return doc


MIGRATORS = {
    "FILL_IN_THE_BLANK_DRAG_DROP": migrate_fill_in_blank_drag_drop,
    "IMAGE_LABELLING_DRAG_DROP": migrate_image_labelling,
}


def migrate_record(record, status):
    question_id = record.get("question_id", "unknown")
    resp = record.get("response", {})
    aat_type = resp.get("type", "")
    migrator = MIGRATORS.get(aat_type)
    if not migrator:
        raise ValueError(f"Unsupported type {aat_type!r}")
    return migrator(resp, status, question_id=question_id)


class DNDTransformer:

    def __init__(self, raw):
        self.raw = raw

    def transform(self):
        q = self.raw.get("response", self.raw)
        q_type = q.get("type")
        if q_type == "FILL_IN_THE_BLANK_DRAG_DROP":
            return migrate_fill_in_blank_drag_drop(q, LIFECYCLE_STATUS)
        if q_type == "IMAGE_LABELLING_DRAG_DROP":
            return migrate_image_labelling(q, LIFECYCLE_STATUS)
        raise ValueError(f"Unsupported DND type: {q_type}")
