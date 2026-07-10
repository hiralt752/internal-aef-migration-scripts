from helpers.mathml_converter import process_html_and_convert_math
from helpers.feedback_mapper import map_hints_and_feedback
from helpers.language_mapper import (
    languageMapper
)
from bs4 import BeautifulSoup
import urllib.parse
from builders.modal_feedback_builder import build_modal_feedback
from parsers.content_parser import parse_html_content

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
    """Return the universal parser's sanitized HTML text block."""
    if not html_content:
        return ""

    parsed_contents = parse_html_content(
        html_content,
        question_id,
        lesson
    )

    for content in parsed_contents:
        if content.get("type") == "text":
            return content.get("text", "")

    return ""


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

    prompt = body.get("prompt")
    if prompt:
        html_fragments.append(prompt)

    for field_name in (
        "generalFeedback",
        "correctAnswerFeedback",
        "wrongAnswerFeedback",
        "partialAnswerFeedback",
    ):
        value = body.get(field_name)
        if value:
            html_fragments.append(value)

    for hint in body.get("hints", []) or []:
        if hint:
            html_fragments.append(hint)

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

        outcomes = metadata_source.get("curriculumOutcomes", [])
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
                "instruction": None,
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
                        "content": {
                            "type": "text",
                            "text": _process_html_preserving_tags(
                                item.get("value", ""), self.question_id, self.lesson
                            ),
                        },
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
                        "content": {
                            "type": "text",
                            "text": _process_html_preserving_tags(
                                item.get("value", ""), self.question_id, self.lesson
                            ),
                        },
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

        if body.get("prompt"):
            qb_payload["itemBody"]["statement"] = {
                "content": [
                    {
                        "type": "text",
                        "text": _process_html_preserving_tags(
                            body.get("prompt"), self.question_id, self.lesson
                        ),
                    }
                ]
            }

        feedback_block = {}
        if body.get("correctAnswerFeedback"):
            feedback_block["correct"] = {
                "content": [
                    {
                        "type": "text",
                        "text": _process_html_preserving_tags(
                            body.get("correctAnswerFeedback"), self.question_id, self.lesson
                        ),
                    }
                ]
            }
        if body.get("wrongAnswerFeedback"):
            feedback_block["incorrect"] = {
                "content": [
                    {
                        "type": "text",
                        "text": _process_html_preserving_tags(
                            body.get("wrongAnswerFeedback"), self.question_id, self.lesson
                        ),
                    }
                ]
            }
        if body.get("partialAnswerFeedback"):
            feedback_block["partial"] = {
                "content": [
                    {
                        "type": "text",
                        "text": _process_html_preserving_tags(
                            body.get("partialAnswerFeedback"), self.question_id, self.lesson
                        ),
                    }
                ]
            }
        if feedback_block:
            qb_payload["outcomeDeclaration"]["feedback"] = feedback_block
        else :
            qb_payload["outcomeDeclaration"]["feedback"] = {
                                                                "correct": {},
                                                                "incorrect": {},
                                                                "partial":{}
                                                            }

        if body.get("generalFeedback"):
            qb_payload["outcomeDeclaration"]["seeWhy"] = {
                "layout": "TEXT",
                "content": [
                    {
                        "type": "text",
                        "text": _process_html_preserving_tags(
                            body.get("generalFeedback"), self.question_id, self.lesson
                        ),
                    }
                ],
                "audio": None,
            }

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

        feedback_mapping = map_hints_and_feedback(
            body.get("hints", []),
            body.get("wrongAnswerFeedback", ""),self.question_id,self.lesson
        )
        modal_feedback = build_modal_feedback(
            self.raw,
            feedback_mapping
        )

        if modal_feedback:
            qb_payload["modalFeedback"] = (
                modal_feedback
            )

        return qb_payload
