from builders.metadata_builder import build_metadata
from builders.itembody_builder import build_item_body
from builders.outcome_builder import build_outcome_declaration
from builders.response_builder import build_response_declaration
from builders.modal_feedback_builder import build_modal_feedback
from helpers.feedback_mapper import map_hints_and_feedback
from helpers.fib_mapper import map_fib_structure


class FIBTransformer:

    def __init__(self, raw):
        self.raw = raw

    def transform(self):
        body = self.raw.get(
            "body",
            {}
        )

        fib_data = map_fib_structure(self.raw)

        feedback_mapping = (
            map_hints_and_feedback(
                body.get("hints", []),
                body.get(
                    "wrongAnswerFeedback",
                    ""
                )
            )
        )

        payload = {
            "schemaVersion": {
                "major": 1,
                "minor": 0,
                "patch": 0
            },
            "type": "FILL_IN_THE_BLANK",
            "subType": "BLANK_ON_TEXT",
            "metadata": build_metadata(self.raw),
            "itemBody": build_item_body(
                self.raw,
                question_type="FIB",
                fib_data=fib_data
            ),
            "responseDeclaration": build_response_declaration(
                self.raw,
                multiple_answer=False,
                question_type="FIB"
            ),
            "outcomeDeclaration": build_outcome_declaration(
                self.raw,
                question_type="FIB",
                fib_data=fib_data
            )
        }

        modal_feedback = (
            build_modal_feedback(
                self.raw,
                feedback_mapping
            )
        )

        if modal_feedback:
            payload["modalFeedback"] = modal_feedback

        return payload
