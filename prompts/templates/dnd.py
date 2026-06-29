from prompts.templates.common import (
    build_question_header,
    compact_join,
    format_list,
    format_options,
    format_correct_answers,
    format_images,
    format_targets,
    unique_question_text_sections
)


def build_dnd_prompt(data):
    sections = [
        build_question_header(data),
        *unique_question_text_sections(data),
        format_targets(data.get("targets", [])),
        format_options(data.get("options", [])),
        format_correct_answers(data.get("correct_answers", [])),
        format_images(data.get("images", [])),
        format_list("Hints", data.get("hints", [])),
        format_list("Feedback", data.get("feedback", [])),
        "Task: classify this drag-and-drop question. Use target positions for image-based items. Return JSON only."
    ]

    return compact_join(sections)
