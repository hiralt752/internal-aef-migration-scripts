from builders.metadata_builder import build_metadata

from builders.image_labelling_dnd_itembody_builder import (
    build_image_labelling_dnd_item_body
)

from builders.fib_dnd_outcome_builder import (
    build_dnd_outcome_declaration
)


class ImageLabellingDNDTransformer:

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

            "subType": "IMAGE_ON_IMAGE",

            "metadata":
                build_metadata(
                    self.raw
                ),

            "itemBody":
                build_image_labelling_dnd_item_body(
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