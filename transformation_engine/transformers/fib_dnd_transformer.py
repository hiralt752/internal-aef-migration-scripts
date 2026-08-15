from builders.metadata_builder import build_metadata
from helpers.feedback_mapper import map_hints_and_feedback
from builders.fib_dnd_itembody_builder import (
    build_fib_dnd_item_body
)
from builders.modal_feedback_builder import build_modal_feedback
from builders.fib_dnd_outcome_builder import (
    build_dnd_outcome_declaration
)


# class DNDTransformer:

#     def __init__(self, raw):
#         self.raw = raw

#     def transform(self):
#         q = self.raw.get("response", self.raw)
#         q_type = q.get("type")
#         if q_type == "FILL_IN_THE_BLANK_DRAG_DROP":
#             return migrate_fill_in_blank_drag_drop(q, LIFECYCLE_STATUS)
#         if q_type == "IMAGE_LABELLING_DRAG_DROP":
#             return migrate_image_labelling(q, LIFECYCLE_STATUS)
#         raise ValueError(f"Unsupported DND type: {q_type}")


class FIBDNDTransformer:

    def __init__(self, raw, question_id, lesson, file_path=None):

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

        item_body = build_fib_dnd_item_body(
            self.raw,
            self.question_id,
            self.lesson,
            self.file_path
        )

        # A non-math image pulled out of the prompt into sideImage means the
        # question is laid out as a split-screen (image beside the blanks)
        # rather than blanks inline with the question text.
        sub_type = (
            "SPLIT_SCREEN"
            if item_body.get("sideImage")
            else "BLANK_ON_QUESTION"
        )

        payload = {

            "schemaVersion": {

                "major": 1,
                "minor": 0,
                "patch": 0
            },

            "type": "DND",

            "subType": sub_type,

            "metadata":
                build_metadata(
                    self.raw
                ),

            "itemBody": item_body,

            "responseDeclaration": {
                "maxAttempts": 1
            },

            "outcomeDeclaration":
                build_dnd_outcome_declaration(
                    self.raw,
                    self.question_id,
                    self.lesson
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
