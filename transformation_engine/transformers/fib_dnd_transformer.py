from builders.metadata_builder import build_metadata

from builders.fib_dnd_itembody_builder import (
    build_fib_dnd_item_body
)

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

    def __init__(self, raw, question_id, lesson):

        self.raw = raw
        self.question_id = question_id
        self.lesson = lesson

    def transform(self):

        payload = {

            "schemaVersion": {

                "major": 1,
                "minor": 0,
                "patch": 0
            },

            "type": "DND",

            "subType": "BLANK_ON_QUESTION",

            "metadata":
                build_metadata(
                    self.raw
                ),

            "itemBody":
                build_fib_dnd_item_body(
                    self.raw,
                    self.question_id,
                    self.lesson
                ),

            "responseDeclaration": {
                "maxAttempts": 1
            },

            "outcomeDeclaration":
                build_dnd_outcome_declaration(
                    self.raw
                )
        }

        return payload
