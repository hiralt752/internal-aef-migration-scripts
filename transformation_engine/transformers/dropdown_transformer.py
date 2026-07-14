"""
Module for transforming legacy Dropdown questions into the new schema.
Contains parsers for blanks, hints, and the main DropdownTransformer.
"""

import re
from html.parser import HTMLParser
from typing import Dict, List, Optional, Tuple
from bs4 import BeautifulSoup
from builders.metadata_builder import build_metadata
from builders.modal_feedback_builder import build_modal_feedback as build_shared_modal_feedback
from parsers.content_parser import strip_disallowed_tags, parse_html_content, ALLOWED_TAGS
from helpers.feedback_mapper import map_hints_and_feedback
from helpers.span_remover import remove_span_texts_from_html
from builders.itembody_builder import _extract_side_image_from_sentence
import json
import os
import threading

failed_file = "failed.json"
mixed_asset_file = "text_asset_mixed.json"
_log_file_lock = threading.Lock()


def _append_json_log(file_path: str, payload: Dict, status: str = "failed") -> None:
    """Append one record to a JSON log file safely across worker threads."""
    with _log_file_lock:
        data = {"status": status, "question_ids": []}

        if os.path.exists(file_path):
            try:
                with open(file_path, "r", encoding="utf-8") as file:
                    loaded = json.load(file)
                if isinstance(loaded, dict):
                    data["status"] = loaded.get("status", status)
                    existing = loaded.get("question_ids", [])
                    if isinstance(existing, list):
                        data["question_ids"] = existing
            except (json.JSONDecodeError, OSError):
                # Recover from empty, partially written, or malformed files.
                pass

        data["question_ids"].append(payload)

        temp_file = f"{file_path}.tmp"
        with open(temp_file, "w", encoding="utf-8") as file:
            json.dump(data, file, ensure_ascii=False, indent=4)
        os.replace(temp_file, file_path)


def dropdown_strict_strip_tags(html_content: str) -> str:
    """Safely unwraps disallowed tags, properly handling nested structures."""
    if not html_content:
        return ""
    soup = BeautifulSoup(html_content, "html.parser")
    while True:
        disallowed_tags = [tag for tag in soup.find_all(True) if tag.name not in ALLOWED_TAGS]
        if not disallowed_tags:
            break
        for tag in disallowed_tags:
            tag.unwrap()
    return str(soup)

def sanitize_blocks(blocks: List[Dict]) -> List[Dict]:
    """Applies strict strip tags to the text fields of parsed blocks and removes empty text blocks."""
    if not blocks:
        return blocks
    sanitized = []
    for b in blocks:
        if b.get("type") == "text":
            cleaned = dropdown_strict_strip_tags(b.get("text", "")).strip()
            if cleaned:
                b["text"] = cleaned
                sanitized.append(b)
        else:
            if b.get("type") == "image" and "text" not in b:
                b["text"] = "Image"  # Target API requires text field even for images in feedback
            sanitized.append(b)
    return sanitized

class BlankFieldParser(HTMLParser):
    """
    Parses HTML to extract blank-field IDs in order of appearance.
    """
    def __init__(self):
        """Initializes the BlankFieldParser with an empty list of IDs."""
        super().__init__()
        self.blank_ids: List[int] = []

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]):
        """
        Handles start tags, specifically capturing the 'id' of 'blank-field' tags.
        
        Args:
            tag (str): The HTML tag name.
            attrs (List[Tuple[str, Optional[str]]]): The tag attributes.
        """
        if tag == "blank-field":
            for name, value in attrs:
                if name == "id" and value:
                    try:
                        self.blank_ids.append(int(value))
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
    """
    Extracts ordered blank IDs from prompt HTML.
    
    Args:
        prompt_html (str): The HTML string containing blank fields.
        
    Returns:
        List[int]: An ordered list of blank IDs.
    """
    if not prompt_html:
        return []
    parser = BlankFieldParser()
    parser.feed(prompt_html)
    return parser.blank_ids


def filter_blank_ids_with_options(body: Dict, blank_ids_ordered: List[int]) -> List[int]:
    """
    Keeps only blank IDs that have at least one available choice.
    """
    blanks_obj = body.get("blanks") or {}
    blank_items_list = blanks_obj.get("blankItems") or []
    blank_items_by_id = {item.get("id"): item for item in blank_items_list}

    valid_blank_ids = []
    for blank_id in blank_ids_ordered:
        blank_item = blank_items_by_id.get(blank_id, {})
        choices = blank_item.get("choices") or []
        if choices:
            valid_blank_ids.append(blank_id)
    return valid_blank_ids


def extract_prompt_media(prompt_html: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Extracts the first audio and video URLs from the prompt HTML.
    
    Args:
        prompt_html (str): The HTML string.
        
    Returns:
        Tuple[Optional[str], Optional[str]]: The audio URL and video URL, if found.
    """
    if not prompt_html:
        return None, None

    audio = re.search(r'<audio[^>]+src=["\']([^"\']+)["\']', prompt_html, re.IGNORECASE)
    if not audio:
        audio = re.search(r'<audio[^>]*>.*?<source[^>]+src=["\']([^"\']+)["\']', prompt_html, flags=re.DOTALL | re.IGNORECASE)

    video = re.search(r'<video[^>]+src=["\']([^"\']+)["\']', prompt_html, re.IGNORECASE)
    if not video:
        video = re.search(r'<video[^>]*>.*?<source[^>]+src=["\']([^"\']+)["\']', prompt_html, flags=re.DOTALL | re.IGNORECASE)

    return (audio.group(1) if audio else None, video.group(1) if video else None)


def replace_blank_fields_with_placeholder(prompt_html: str) -> Optional[str]:
    """
    Replaces blank-field tags with '@_@' and removes media tags.
    
    Args:
        prompt_html (str): The original prompt HTML.
        
    Returns:
        Optional[str]: The sanitized string with placeholders, or None if empty.
    """
    html = re.sub(r'<blank-field[^>]*>.*?</blank-field>', '@_@', prompt_html or "", flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r'<audio[^>]*>.*?</audio>', '', html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r'<audio[^>]*/>', '', html, flags=re.IGNORECASE)
    html = re.sub(r'<video[^>]*>.*?</video>', '', html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r'<video[^>]*/>', '', html, flags=re.IGNORECASE)
    result = html.replace("\r\n", "").replace("\n", "").replace("\r", "").strip()
    return result if result else None


def parse_choice_content(value_html: str, opt_id: int, question_id=None, lesson=None) -> Dict:
    """
    Parses choice content into structured text or image objects.
    WIRIS math formulas are cleanly extracted as LaTeX text strings by parse_html_content.
    If a legacy option is genuinely empty, this will intentionally return an empty string
    so that downstream API validation throws a visible error to flag the bad data.
    """
    if not value_html:
        return {"type": "text", "text": ""}
    parsed_contents = parse_html_content(value_html, question_id, lesson)

    if len(parsed_contents) > 1:
        _append_json_log(
            failed_file,
            {
                "question_id": question_id,
                "option_id": opt_id,
                "value": parsed_contents,
            },
        )

    has_text = any(item.get("type") == "text" for item in parsed_contents)
    asset_types = [
        item.get("type")
        for item in parsed_contents
        if item.get("type") in ("image", "audio", "video")
    ]
    if len(parsed_contents) > 2 or (has_text and asset_types):
        _append_json_log(
            mixed_asset_file,
            {
                "question_id": question_id,
                "option_id": opt_id,
                "asset_types": asset_types,
                "value_html": value_html,
                "parsed_contents": parsed_contents,
            },
            status="mixed_text_asset",
        )

    for item in parsed_contents:
        if item.get("type") == "image":
            return {
                "type": "image",
                "image": item.get("image"),
                "text":""
            }

        if item.get("type") == "text":
            # Target API completely rejects HTML tags in Dropdown options.
            # We use BeautifulSoup get_text() to strip all tags (like <p>, <span>)
            # but this correctly preserves LaTeX strings like "\( ... \)" which have no tags.
                return {"type": "text", "text": item.get("text", "")}

    return {"type": "text", "text": ""}


class _ParsedHint:
    def __init__(self, items):
        self.items = items
    def has_media(self) -> bool:
        return any(i["type"] in ("image", "audio", "video") for i in self.items)
    def text_only_items(self) -> List[Dict]:
        return [i for i in self.items if i["type"] == "text"]
    def media_only_items(self) -> List[Dict]:
        return [i for i in self.items if i["type"] != "text"]
    
def run_hint_mapper(wrong_answer_feedback_html: str, hints_html: List[str]) -> Tuple[Optional[List[Dict]], Optional[List[Dict]]]:
    """
    Maps legacy hints and wrongAnswerFeedback into structured target API JSON blocks.
    """
    waf_items = sanitize_blocks(parse_html_content(wrong_answer_feedback_html or "", None, None))
    has_waf = bool(waf_items)

    parsed_hints = []
    for h in (hints_html or []):
        items = sanitize_blocks(parse_html_content(h, None, None)) if h else []
        if items:
            parsed_hints.append(_ParsedHint(items))
            
    n = len(parsed_hints)

    if has_waf:
        need_help: List[Dict] = []
        for hint in parsed_hints:
            need_help.extend(hint.items)
        return waf_items, (need_help if need_help else None)

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


def build_item_body(body: Dict,qid:str) -> Dict:
    """
    Builds the main itemBody structure for a Dropdown question, handling options and weights.
    
    Args:
        body (Dict): The legacy body payload.
        
    Returns:
        Dict: The transformed itemBody JSON structure.
    """
    prompt_html = body.get("prompt", "") or ""
    blank_ids_ordered = extract_blank_ids_in_order(prompt_html)
    blank_ids_ordered = filter_blank_ids_with_options(body, blank_ids_ordered)
    audio_url, video_url = extract_prompt_media(prompt_html)
    sentence_text = replace_blank_fields_with_placeholder(prompt_html)

    blanks_obj = body.get("blanks") or {}
    shuffled = blanks_obj.get("shuffle", True)
    blank_items_list = blanks_obj.get("blankItems") or []
    blank_items_by_id = {item.get("id"): item for item in blank_items_list}

    items = []
    total_blanks = len(blank_ids_ordered)
    running_weight_sum = 0.0
    for incremental_id, aat_blank_id in enumerate(blank_ids_ordered, start=1):
        blank_item = blank_items_by_id.get(aat_blank_id, {})
        raw_weight = blank_item.get("weight", 100.0)
        weight = round(raw_weight / 100.0, 6)

        if incremental_id == total_blanks and total_blanks > 0:
            weight = round(max(0.0, 1.0 - running_weight_sum), 6)
        else:
            weight = round(raw_weight / 100.0, 6)
            running_weight_sum += weight
        choices = blank_item.get("choices") or []
        options = []
        for opt_id, choice in enumerate(choices, start=1):
            raw_feedback = choice.get("feedback", "")
            parsed_fb = parse_html_content(raw_feedback, None, None)
            fb_text = "".join([b["text"] for b in parsed_fb if b.get("type") == "text"]).strip()
            fb_final = dropdown_strict_strip_tags(fb_text)

            options.append({
                "id": opt_id,
                "content": parse_choice_content(choice.get("value", ""), opt_id,qid),
                "feedback": fb_final,
            })

        items.append({
            "id": incremental_id,
            "weight": weight,
            "title": None,
            "subtitle": None,
            "image": None,
            "options": options,
        })

    if items:
        total_weight = sum(item["weight"] for item in items)
        if total_weight > 0 and round(total_weight, 4) != 1.0:
            diff = 1.0 - total_weight
            items[0]["weight"] = round(items[0]["weight"] + diff, 4)

    parsed_sentence = parse_html_content(sentence_text, None, None)
    sentence_raw = "".join([b["text"] for b in parsed_sentence if b.get("type") == "text"]).strip()
    sentence_final = dropdown_strict_strip_tags(sentence_raw)

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
        "sentence": {"text": sentence_final},
        "items": items,
    }


def build_outcome_declaration(body: Dict, validation: Dict, blank_ids_ordered: List[int]) -> Dict:
    """
    Builds the outcomeDeclaration mapping for correctness logic and feedback.
    
    Args:
        body (Dict): The legacy body payload.
        validation (Dict): The legacy validation payload.
        blank_ids_ordered (List[int]): List of sequential blank IDs.
        
    Returns:
        Dict: The outcomeDeclaration JSON structure.
    """
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
    general_items = sanitize_blocks(parse_html_content(general_fb_html, None, None))
    if general_items:
        see_why = {
            "layout": "TEXT",
            "content": general_items,
        }

    incorrect_items, _need_help_items = run_hint_mapper(
        wrong_answer_feedback_html=body.get("wrongAnswerFeedback") or "",
        hints_html=body.get("hints") or [],
    )

    feedback: Dict = {}
    correct_html = body.get("correctAnswerFeedback") or ""
    correct_text = dropdown_strict_strip_tags(correct_html).strip()
    if correct_text:
        feedback["correct"] = {"content": [{"type": "text", "text": correct_text}]}

    if incorrect_items:
        feedback["incorrect"] = {"content": incorrect_items}

    partial_items = sanitize_blocks(parse_html_content(body.get("partialAnswerFeedback") or "", None, None))
    if partial_items:
        feedback["partial"] = {"content": partial_items}

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
    """
    Builds the modalFeedback mapping for need-help sections and passages.
    
    Args:
        body (Dict): The legacy body payload.
        
    Returns:
        Optional[Dict]: The modalFeedback structure or None if not applicable.
    """
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
    """
    Orchestrates the complete transformation of a legacy DROPDOWN question 
    into the new strict JSON schema.
    """
    def __init__(self, raw: Dict, qid, lesson, file_path):
        """
        Initializes the DropdownTransformer with raw legacy payload.
        
        Args:
            raw (Dict): The original legacy question JSON.
        """
        self.raw = raw
        self.qid = qid
        self.lesson = lesson
        self.file_path = file_path

    def transform(self) -> Dict:
        """
        Executes the transformation process.
        
        Returns:
            Dict: The fully transformed new schema JSON payload.
        """
        q = self.raw.get("response", self.raw)
        body = q.get("body") or {}
        validation = q.get("validation") or {}
        prompt_html = body.get("prompt") or ""
        prompt_html = remove_span_texts_from_html(prompt_html, self.qid, self.lesson, self.file_path)
        blank_ids_ordered = extract_blank_ids_in_order(prompt_html)
        blank_ids_ordered = filter_blank_ids_with_options(body, blank_ids_ordered)
        feedback_mapping = map_hints_and_feedback(
            body.get("hints", []),
            body.get("wrongAnswerFeedback", ""),
            self.qid,
            self.lesson,
        )

        payload = {
            "schemaVersion": {"major": 1, "minor": 0, "patch": 0},
            "type": "DROPDOWN",
            "subType": "DROPDOWN_SENTENCE",
            "metadata": build_metadata(q),
            "itemBody": build_item_body(body,self.qid),
            "responseDeclaration": {"maxAttempts": 1},
            "outcomeDeclaration": build_outcome_declaration(body, validation, blank_ids_ordered),
        }

        modal_feedback = build_shared_modal_feedback(
            self.raw,
            feedback_mapping,
        )
        if modal_feedback:
            payload["modalFeedback"] = modal_feedback

        return payload
