import re
from html.parser import HTMLParser
from typing import Dict, List, Optional, Tuple

from builders.metadata_builder import build_metadata
from parsers.content_parser import parse_html_content


class BlankFieldParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.blank_ids: List[int] = []

    def handle_starttag(self, tag, attrs):
        if tag == "blank-field":
            attrs_dict = dict(attrs)
            if "id" in attrs_dict:
                try:
                    self.blank_ids.append(int(attrs_dict["id"]))
                except ValueError:
                    pass


class HintMediaParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self._current_text: List[str] = []
        self.items: List[Dict] = []

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        if tag == "img":
            self._flush_text()
            src = attrs_dict.get("src", "")
            if src.startswith("data:image/svg+xml") and "MathML" in src:
                return
            if src:
                self.items.append({"type": "image", "image": {"url": src}})
        elif tag == "audio":
            self._flush_text()
            src = attrs_dict.get("src", "")
            if src:
                self.items.append({"type": "audio", "audio": {"url": src}})
        elif tag == "video":
            self._flush_text()
            src = attrs_dict.get("src", "")
            if src:
                self.items.append({"type": "video", "video": {"url": src}})

    def handle_data(self, data):
        self._current_text.append(data)

    def handle_entityref(self, name):
        entities = {"nbsp": " ", "amp": "&", "lt": "<", "gt": ">", "quot": '"', "apos": "'"}
        self._current_text.append(entities.get(name, ""))

    def handle_charref(self, name):
        try:
            code = int(name[1:], 16) if name.startswith("x") else int(name)
            self._current_text.append(chr(code))
        except (ValueError, OverflowError):
            pass

    def _flush_text(self):
        text = "".join(self._current_text).strip()
        if text:
            self.items.append({"type": "text", "text": text})
        self._current_text = []

    def close(self):
        self._flush_text()
        super().close()

    def has_media(self) -> bool:
        return any(item["type"] in ("image", "audio", "video") for item in self.items)

    def text_only_items(self) -> List[Dict]:
        return [item for item in self.items if item["type"] == "text"]

    def media_only_items(self) -> List[Dict]:
        return [item for item in self.items if item["type"] != "text"]


def parse_hint(hint_html: str) -> HintMediaParser:
    parser = HintMediaParser()
    parser.feed(hint_html or "")
    parser.close()
    return parser


def extract_blank_ids_in_order(prompt_html: str) -> List[int]:
    parser = BlankFieldParser()
    parser.feed(prompt_html or "")
    return parser.blank_ids


def extract_prompt_media(prompt_html: str) -> Tuple[Optional[str], Optional[str]]:
    audio = re.search(r'<audio[^>]+src=["\']([^"\']+)["\']', prompt_html or "", re.IGNORECASE)
    video = re.search(r'<video[^>]+src=["\']([^"\']+)["\']', prompt_html or "", re.IGNORECASE)
    return (audio.group(1) if audio else None, video.group(1) if video else None)


def replace_blank_fields_with_placeholder(prompt_html: str) -> Optional[str]:
    html = re.sub(r'<blank-field[^>]*>.*?</blank-field>', '@_@', prompt_html or "", flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r'<audio[^>]*>.*?</audio>', '', html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r'<audio[^>]*/>', '', html, flags=re.IGNORECASE)
    html = re.sub(r'<video[^>]*>.*?</video>', '', html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r'<video[^>]*/>', '', html, flags=re.IGNORECASE)
    result = html.replace("\r\n", "").replace("\n", "").replace("\r", "").strip()
    return result if result else None


def strip_html_tags(html: str) -> str:
    clean = re.sub(r'<[^>]+>', '', html or '')
    for entity, char in [('&nbsp;', ' '), ('&amp;', '&'), ('&lt;', '<'), ('&gt;', '>'), ('&quot;', '"'), ('&#39;', "'")]:
        clean = clean.replace(entity, char)
    return clean.strip()


def parse_choice_content(value_html: str) -> Dict:
    if not value_html:
        return {"type": "text", "text": ""}
    img = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', value_html, re.IGNORECASE)
    if img:
        return {"type": "image", "image": {"url": img.group(1)}}
    return {"type": "text", "text": strip_html_tags(value_html)}


def run_hint_mapper(wrong_answer_feedback_html: str, hints_html: List[str]) -> Tuple[Optional[List[Dict]], Optional[List[Dict]]]:
    waf_text = strip_html_tags(wrong_answer_feedback_html or "")
    has_waf = bool(waf_text)

    parsed_hints = [parse_hint(h) for h in (hints_html or [])]
    parsed_hints = [hint for hint in parsed_hints if hint.items]
    n = len(parsed_hints)

    if has_waf:
        waf_parser = parse_hint(wrong_answer_feedback_html)
        incorrect = waf_parser.items if waf_parser.items else [{"type": "text", "text": waf_text}]
        need_help: List[Dict] = []
        for hint in parsed_hints:
            need_help.extend(hint.items)
        return incorrect, (need_help if need_help else None)

    if n == 0:
        return None, None

    if n == 1 and not parsed_hints[0].has_media():
        text_items = parsed_hints[0].text_only_items()
        return (text_items if text_items else None), None

    if n == 1 and parsed_hints[0].has_media():
        return None, parsed_hints[0].items

    last = parsed_hints[-1]
    earlier = parsed_hints[:-1]
    incorrect = last.text_only_items() or None
    need_help: List[Dict] = []
    for hint in earlier:
        need_help.extend(hint.items)
    need_help.extend(last.media_only_items())
    return incorrect, (need_help if need_help else None)


def build_item_body(body: Dict) -> Dict:
    prompt_html = body.get("prompt", "") or ""
    blank_ids_ordered = extract_blank_ids_in_order(prompt_html)
    audio_url, video_url = extract_prompt_media(prompt_html)
    sentence_text = replace_blank_fields_with_placeholder(prompt_html)

    blanks_obj = body.get("blanks") or {}
    shuffled = blanks_obj.get("shuffle", True)
    blank_items_list = blanks_obj.get("blankItems") or []
    blank_items_by_id = {item.get("id"): item for item in blank_items_list}

    items = []
    for incremental_id, aat_blank_id in enumerate(blank_ids_ordered, start=1):
        blank_item = blank_items_by_id.get(aat_blank_id, {})
        raw_weight = blank_item.get("weight", 100.0)
        weight = round(raw_weight / 100.0, 6)
        choices = blank_item.get("choices") or []
        options = []
        for opt_id, choice in enumerate(choices, start=1):
            options.append({
                "id": opt_id,
                "content": parse_choice_content(choice.get("value", "")),
                "feedback": choice.get("feedback", ""),
            })

        items.append({
            "id": incremental_id,
            "weight": weight,
            "title": None,
            "subtitle": None,
            "image": None,
            "options": options,
        })

    return {
        "version": "1.0",
        "title": None,
        "subTitle": None,
        "instruction": None,
        "audio": {"url": audio_url} if audio_url else None,
        "video": {"url": video_url} if video_url else None,
        "backgroundLayout": None,
        "timeSpentConfig": None,
        "splitContent": None,
        "sideImage": None,
        "shuffled": shuffled,
        "statement": None,
        "sentence": {"text": sentence_text},
        "items": items,
    }


def build_outcome_declaration(body: Dict, validation: Dict, blank_ids_ordered: List[int]) -> Dict:
    blanks_obj = body.get("blanks") or {}
    blank_items_list = blanks_obj.get("blankItems") or []
    blank_id_to_incremental = {aat_id: idx + 1 for idx, aat_id in enumerate(blank_ids_ordered)}

    option_id_lookup: Dict[Tuple[int, int], int] = {}
    for blank_item in blank_items_list:
        aat_blank_id = blank_item.get("id")
        for opt_idx, choice in enumerate(blank_item.get("choices") or [], start=1):
            option_id_lookup[(aat_blank_id, choice.get("id"))] = opt_idx

    scoring_type = validation.get("scoringType", "EXACT_MATCH")
    valid_blank_choices = (validation.get("validResponse") or {}).get("validBlankChoices") or []

    correct_answers = []
    for vbc in valid_blank_choices:
        aat_blank_id = vbc.get("blankId")
        aat_choice_id = vbc.get("choiceId")
        dropdown_id = blank_id_to_incremental.get(aat_blank_id)
        option_id = option_id_lookup.get((aat_blank_id, aat_choice_id))
        if dropdown_id is not None and option_id is not None:
            correct_answers.append({"dropDownId": dropdown_id, "optionId": option_id})

    see_why = None
    general_fb_html = body.get("generalFeedback") or ""
    general_fb_text = strip_html_tags(general_fb_html)
    if general_fb_text:
        see_why = {
            "layout": "TEXT",
            "content": [{"type": "text", "text": general_fb_text}],
        }

    incorrect_items, _need_help_items = run_hint_mapper(
        wrong_answer_feedback_html=body.get("wrongAnswerFeedback") or "",
        hints_html=body.get("hints") or [],
    )

    feedback: Dict = {}
    correct_fb_text = strip_html_tags(body.get("correctAnswerFeedback") or "")
    if correct_fb_text:
        feedback["correct"] = {"content": [{"type": "text", "text": correct_fb_text}]}

    if incorrect_items:
        feedback["incorrect"] = {"content": incorrect_items}

    partial_fb_text = strip_html_tags(body.get("partialAnswerFeedback") or "")
    if partial_fb_text:
        feedback["partial"] = {"content": [{"type": "text", "text": partial_fb_text}]}

    outcome: Dict = {
        "scoringType": scoring_type,
        "scoring": {
            "normalizedMin": 0,
            "normalizedMax": 1,
            "defaultNormalizedValue": 0,
        },
    }

    if feedback:
        outcome["feedback"] = feedback

    if see_why:
        outcome["seeWhy"] = see_why

    outcome["validResponse"] = {
        "shouldAutoGraded": True,
        "correctAnswers": correct_answers,
    }

    return outcome


def build_modal_feedback(body: Dict) -> Optional[Dict]:
    _incorrect_items, need_help_items = run_hint_mapper(
        wrong_answer_feedback_html=body.get("wrongAnswerFeedback") or "",
        hints_html=body.get("hints") or [],
    )

    passage = body.get("passage")
    passage_id = None
    if isinstance(passage, dict):
        passage_id = passage.get("id")
    elif isinstance(passage, str) and passage:
        passage_id = passage

    has_need_help = bool(need_help_items)
    has_passage = bool(passage_id)
    if not has_need_help and not has_passage:
        return None

    modal: Dict = {}
    if has_need_help:
        modal["needHelp"] = {
            "content": {
                "layout": "TEXT",
                "content": need_help_items,
            }
        }
    if has_passage:
        modal["passageId"] = passage_id

    return modal


class DropdownTransformer:
    def __init__(self, raw: Dict):
        self.raw = raw

    def transform(self) -> Dict:
        q = self.raw.get("response", self.raw)
        body = q.get("body") or {}
        validation = q.get("validation") or {}
        prompt_html = body.get("prompt") or ""
        blank_ids_ordered = extract_blank_ids_in_order(prompt_html)

        payload = {
            "schemaVersion": {"major": 1, "minor": 0, "patch": 0},
            "type": "DROPDOWN",
            "subType": "DROPDOWN_SENTENCE",
            "metadata": build_metadata(q),
            "itemBody": build_item_body(body),
            "responseDeclaration": {"maxAttempts": 1},
            "outcomeDeclaration": build_outcome_declaration(body, validation, blank_ids_ordered),
        }

        modal_feedback = build_modal_feedback(body)
        if modal_feedback:
            payload["modalFeedback"] = modal_feedback

        return payload
