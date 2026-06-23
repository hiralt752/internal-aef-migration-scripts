from builders.metadata_builder import build_metadata
from builders.itembody_builder import build_item_body
from builders.outcome_builder import build_outcome_declaration
from builders.response_builder import build_response_declaration
from builders.modal_feedback_builder import build_modal_feedback

from helpers.subtype_detector import detect_subtype
from helpers.feedback_mapper import map_hints_and_feedback



class MCQTransformer:

    def __init__(self, raw,question_id,lesson, file_path=None):
        self.raw = raw
        self.question_id = question_id
        self.lesson = lesson
        self.file_path = file_path

    def transform(self):

        body = self.raw.get("body", {})
        feedback_mapping = map_hints_and_feedback(
            body.get("hints", []),
            body.get("wrongAnswerFeedback", ""),
            self.question_id,self.lesson
        )

        payload = {

            "schemaVersion": {
                "major": 1,
                "minor": 0,
                "patch": 0
            },

            "type": "MULTIPLE_CHOICE",

            "subType": detect_subtype(
                body.get("choices", {})
                .get("choiceItems", []),self.question_id,self.lesson
            ),

            "metadata":
                build_metadata(self.raw),

            "itemBody":
                build_item_body(self.raw, question_id=self.question_id, lesson=self.lesson,file_path=self.file_path),

            "responseDeclaration":
                build_response_declaration(
                    self.raw,
                    multiple_answer=False
                ),

            "outcomeDeclaration":
                build_outcome_declaration(
                    self.raw,self.question_id,self.lesson
                )
        }

        modal_feedback = build_modal_feedback(
            self.raw,
            feedback_mapping
        )

        if modal_feedback:
            payload["modalFeedback"] = (
                modal_feedback
            )

        return payload