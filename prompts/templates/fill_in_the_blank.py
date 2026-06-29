from prompts.templates.common import (
    build_question_header,
    compact_join,
    format_list,
    format_correct_answers,
    format_images,
    unique_question_text_sections
)


def build_fill_in_the_blank_prompt(data):
    sections = [
        build_question_header(data),
        *unique_question_text_sections(data),
        format_list("Word Bank / Options", data.get("word_bank", [])),
        format_correct_answers(data.get("correct_answers", [])),
        format_images(data.get("images", [])),
        format_list("Hints", data.get("hints", [])),
        format_list("Feedback", data.get("feedback", [])),
        "Task: classify this fill-in-the-blank question. @_@ marks a blank. Return JSON only."
    ]

    return compact_join(sections)
