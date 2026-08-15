from helpers.mathml_converter import process_html_and_convert_math
from helpers.feedback_mapper import map_hints_and_feedback
from helpers.language_mapper import (
    languageMapper
)
from bs4 import BeautifulSoup
import urllib.parse
from builders.modal_feedback_builder import build_modal_feedback
from builders.metadata_builder import _normalize_curriculum_outcomes
from builders.outcome_builder import build_correct_incorrect_feedback
from parsers.content_parser import parse_html_content
from helpers.span_remover import remove_span_texts_from_html

def _is_wiris_math_image(img_tag):
    src = img_tag.get("src", "") or ""
    classes = img_tag.get("class") or []

    return (
        "Wirisformula" in classes
        or (
            src.startswith("data:image/svg+xml")
            and "mathml" in urllib.parse.unquote(src).lower()
        )
    )


def _process_html_preserving_tags(html_content, question_id=None, lesson=None):
    """Return the universal parser's sanitized HTML text block.

    Used for itemBody.items[].feedback, a plain string field (not a
    ContentItem[]) - extract_table=False keeps any table inline instead of
    pulling it into a separate item that the loop below would then drop.
    """
    if not html_content:
        return ""

    parsed_contents = parse_html_content(
        html_content,
        question_id,
        lesson,
        extract_table=False
    )

    for content in parsed_contents:
        if content.get("type") == "text":
            return content.get("text", "")

    return ""


def _parse_matching_content(html_content, question_id=None, lesson=None):
    if not html_content:
        return {
            "type": "text",
            "text": ""
        }

    parsed_contents = parse_html_content(
        html_content,
        question_id,
        lesson
    )

    for content in parsed_contents:
        if content.get("type") == "image":
            return {
                "type": "image",
                "image": content.get("image"),
                "text":""
            }

        if content.get("type") == "audio":
                    return {
                        "type": "audio",
                        "audio": content.get("audio"),
                        "text":""
                    }

        if content.get("type") == "video":
                    return {
                        "type": "video",
                        "video": content.get("video"),
                        "text":""
                    }
        
        if content.get("type") == "text":
            if content.get("text", ""):
                return {
                    "type": "text",
                    "text": content.get("text", "")
                }

    return {
        "type": "text",
        "text": ""
    }


def _parse_rich_content(html_content, question_id=None, lesson=None, extract_table=True):
    if not html_content:
        return []

    parsed_contents = parse_html_content(
        html_content,
        question_id,
        lesson,
        extract_table=extract_table
    )

    rich_content = []
    for content in parsed_contents:
        content_type = content.get("type")
        if content_type not in ["text", "image", "video", "audio", "table"]:
            continue

        normalized_content = dict(content)
        if content_type in ["image", "video", "audio"]:
            normalized_content["text"] = normalized_content.get("text", "") or ""

        rich_content.append(normalized_content)

    return rich_content


def _detect_html_modalities(html_content):
    soup = BeautifulSoup(html_content or "", "html.parser")

    has_image = False
    for img in soup.find_all("img"):
        if not _is_wiris_math_image(img):
            has_image = True

    has_audio = bool(soup.find("audio"))
    has_video = bool(soup.find("video"))

    for tag in soup.find_all(["img", "audio", "video", "source"]):
        tag.decompose()

    has_text = bool(process_html_and_convert_math(str(soup)).strip())

    return {
        "text": has_text,
        "image": has_image,
        "audio": has_audio,
        "video": has_video,
    }


def check_sub_type(body):
    html_fragments = []

    matchers = body.get("matchers") or {}
    for item in matchers.get("choices", []) or []:
        if item.get("value"):
            html_fragments.append(item.get("value"))
        if item.get("feedback"):
            html_fragments.append(item.get("feedback"))

    for item in matchers.get("answers", []) or []:
        if item.get("value"):
            html_fragments.append(item.get("value"))
        if item.get("feedback"):
            html_fragments.append(item.get("feedback"))

    has_text = False
    has_image = False
    has_audio = False
    has_video = False

    for html_content in html_fragments:
        modalities = _detect_html_modalities(html_content)
        has_text = has_text or modalities["text"]
        has_image = has_image or modalities["image"]
        has_audio = has_audio or modalities["audio"]
        has_video = has_video or modalities["video"]

    if has_video:
        return "MIX"

    if has_audio and not has_text and not has_image:
        return "AUDIO_AUDIO"

    if has_image and not has_text and not has_audio:
        return "IMAGE_IMAGE"

    if has_text and has_image and not has_audio:
        return "TEXT_IMAGE"

    if has_text and not has_image and not has_audio:
        return "TEXT_TEXT"

    if has_audio or has_image or has_text:
        return "MIX"

    return "TEXT_TEXT"


class MatchingTransformer:

    def __init__(self, raw, question_id=None, lesson=None):
        self.raw = raw
        self.question_id = question_id
        self.lesson = lesson

    def transform(self):
        q = self.raw.get("response", self.raw)
        body = q.get("body") or {}
        validation = q.get("validation") or {}
        metadata_source = q.get("metadata") or {}

        source_val = "AAT"

        outcomes = _normalize_curriculum_outcomes(metadata_source.get("curriculumOutcomes", []))
        first_outcome = outcomes[0] if outcomes else {}
        grade = first_outcome.get("grade", "")
        subject = first_outcome.get("subject", "")
        curriculum = first_outcome.get("curriculum", "")

        qb_payload = {
            "schemaVersion": {"major": 1, "minor": 0, "patch": 0},
            "type": "MATCHING",
            "subType": check_sub_type(body),
            "metadata": {
                "general": {
                    "code": q.get("code"),
                    "externalId": q.get("id"),
                    "title": None,
                    "language": languageMapper(q.get("language")),
                    "keywords": metadata_source.get("keywords", []),
                    "parentReference": None,
                    "source": source_val,
                },
                "lifecycle": {
                    "status": "DRAFT",
                },
                "technical": {
                    "penAndPaper": metadata_source.get("penAndPaper", False),
                },
                "educational": {
                    "resourceType": metadata_source.get("resourceType"),
                    "difficultyLevel": metadata_source.get("difficultyLevel"),
                    "cognitiveDimensions": metadata_source.get("cognitiveDimensions", []),
                    "knowledgeDimensions": metadata_source.get("knowledgeDimensions", []),
                    "summativeAssessment": metadata_source.get("summativeAssessment", False),
                    "cefrLevel": metadata_source.get("cefrLevel"),
                    "proficiency": metadata_source.get("proficiency"),
                    "lexileLevel": metadata_source.get("lexileLevel"),
                    "logitValue": metadata_source.get("logitValue"),
                },
                "rights": {
                    "copyrights": metadata_source.get("copyrights", []),
                    "conditionsOfUse": metadata_source.get("conditionsOfUse", []),
                },
                "classification": {
                    "grade": grade,
                    "subject": subject,
                    "curriculum": curriculum,
                    "curriculumOutcomes": outcomes,
                    "subDomain": metadata_source.get("domains", []) or [],
                },
                "annotation": {
                    "tags": {
                        "migration:source": "AAT",
                        "migration:originalCreatedAt": q.get("createdAt"),
                        "migration:authoredDate": metadata_source.get("authoredDate"),
                    }
                },
            },
            "itemBody": {
                "version": "1.0",
                "title": None,
                "subTitle": None,
                "instruction": {"text": _process_html_preserving_tags(body.get("prompt"), self.question_id, self.lesson)} if body.get("prompt") else None,
                "audio": None,
                "video": None,
                "backgroundLayout": None,
                "timeSpentConfig": None,
                "shuffled": body.get("matchers", {}).get("shuffle", True),
                "itemLabel":{
                    "text":""
                },
                "optionLabel":{
                    "text":""
                },
                "items": [
                    {
                        "id": item.get("id"),
                        "weight": item.get("weight", 1.0),
                        "content": _parse_matching_content(
                            item.get("value", ""), self.question_id, self.lesson
                        ),
                        "feedback": (
                            _process_html_preserving_tags(
                                item.get("feedback", ""), self.question_id, self.lesson
                            )
                            if item.get("feedback")
                            else None
                        ),
                    }
                    for item in body.get("matchers", {}).get("choices", [])
                ],
                "options": [
                    {
                        "id": item.get("id"),
                        "content": _parse_matching_content(
                            item.get("value", ""), self.question_id, self.lesson
                        ),
                    }
                    for item in body.get("matchers", {}).get("answers", [])
                ],
            },
            "responseDeclaration": {
                "maxAttempts": 1,
            },
            "outcomeDeclaration": {
                "scoringType": validation.get("scoringType", "EXACT_MATCH"),
                "scoring": {
                    "normalizedMin": 0,
                    "normalizedMax": 1,
                    "defaultNormalizedValue": 0,
                }
            },
        }



        # correct/incorrect follow the same MCQ-derived pattern as the other
        # question types (correctAnswerFeedback -> "correct",
        # wrongAnswerFeedback/hints -> "incorrect", placeholder fallback).
        feedback_mapping = map_hints_and_feedback(
            body.get("hints", []),
            body.get("wrongAnswerFeedback", ""), self.question_id, self.lesson
        )

        feedback_block = build_correct_incorrect_feedback(
            body, self.question_id, self.lesson, feedback_mapping=feedback_mapping
        )

        # feedback.*.content is Html[] (text-only, no "table" field, unlike
        # statement/seeWhy's ContentItem[]) - keep any table inline.
        if body.get("partialAnswerFeedback"):
            partial = _parse_rich_content(
                body.get("partialAnswerFeedback"), self.question_id, self.lesson,
                extract_table=False
            )
            feedback_block["partial"] = {
                "content":partial
            }

        if body.get("generalFeedback"):
            generalFeedback = _parse_rich_content(
                body.get("generalFeedback"), self.question_id, self.lesson
            )
            qb_payload["outcomeDeclaration"]["seeWhy"] = {
                "layout": "TEXT",
                "content":generalFeedback,
                "audio": None,
            }

        if feedback_block:
            qb_payload["outcomeDeclaration"]["feedback"] = feedback_block

        valid_resp = validation.get("validResponse")
        if valid_resp and valid_resp.get("answerMapping"):
            qb_payload["outcomeDeclaration"]["validResponse"] = {
                "correctAnswers": [
                    {
                        "itemId": pair.get("choiceId"),
                        "optionId": pair.get("answerId"),
                    }
                    for pair in valid_resp.get("answerMapping", [])
                ],
            }

        modal_feedback = build_modal_feedback(
            self.raw,
            feedback_mapping
        )

        if modal_feedback:
            qb_payload["modalFeedback"] = (
                modal_feedback
            )

        return qb_payload
