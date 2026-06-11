def build_modal_feedback(
    raw,
    feedback_mapping
):

    body = raw.get("body", {})

    modal = {}

    need_help = (
        feedback_mapping.get(
            "needHelp",
            []
        )
    )

    if need_help:

        modal["needHelp"] = {

            "content": {

                "layout": "TEXT",

                "content":
                    need_help
            }
        }

    passage = body.get("passage")

    if (
        passage
        and passage.get("id")
    ):

        modal["passageId"] = (
            passage.get("id")
        )

    return modal if modal else None