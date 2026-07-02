from builders.metadata_builder import build_metadata

from builders.image_labelling_dnd_itembody_builder import (
    build_image_labelling_dnd_item_body
)

from builders.outcome_builder import build_outcome_declaration

from builders.response_builder import (
    build_response_declaration
)

from builders.modal_feedback_builder import (
    build_modal_feedback
)

from helpers.feedback_mapper import (
    map_hints_and_feedback
)


class ImageLabellingDNDTransformer:

    def __init__(self, raw,question_id,lesson):

        self.raw = raw
        self.question_id= question_id
        self.lesson = lesson

    def transform(self):

        body = self.raw.get(
            "body",
            {}
        )

        feedback_mapping = map_hints_and_feedback(
            body.get(
                "hints",
                []
            ),
            body.get(
                "wrongAnswerFeedback",
                ""
            ),self.question_id,self.lesson
        )

        payload = {

            "schemaVersion": {

                "major": 1,

                "minor": 0,

                "patch": 0
            },

            "type": "DND",

            "subType": "TEXT_ON_IMAGE",

            "metadata":
                build_metadata(
                    self.raw
                ),

            "itemBody":
                build_image_labelling_dnd_item_body(
                    self.raw,self.question_id,self.lesson
                ),

            "responseDeclaration":
                build_response_declaration(
                    self.raw,
                    multiple_answer=False
                ),

            "outcomeDeclaration":
                build_outcome_declaration(
                    self.raw,self.question_id,self.lesson,"IMAGE_LABELLING_DRAG_DROP"
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
            
        def inject_text_field(obj):
            if isinstance(obj, dict):
                # Only add 'text' for specific content types to avoid polluting the root payload or other nodes
                if obj.get('type') in ['audio', 'video', 'image', 'text'] and 'text' not in obj:
                    obj['text'] = ""
                for k, v in obj.items():
                    inject_text_field(v)
            elif isinstance(obj, list):
                for item in obj:
                    inject_text_field(item)

        # Inject text: "" into the payload to satisfy schema validation
        inject_text_field(payload)

        return payload