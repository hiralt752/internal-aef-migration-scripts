from prompts.templates.common import (
    build_question_header,
    compact_join,
    format_list,
    format_correct_answers,
    format_images,
    unique_question_text_sections
)


def format_matching_pairs(pairs):
    if not pairs:
        return ""

    lines = ["Matching Items:"]

    for pair in pairs:
        left = pair.get("left", "")
        right = pair.get("right", "")
        pair_id = pair.get("id", "")

        if pair_id:
            lines.append(f"- Pair ID {pair_id}: {left} -> {right}")
        else:
            lines.append(f"- {left} -> {right}")

    return "\n".join(lines)


def build_matching_prompt(data):
    sections = [
        build_question_header(data),
        *unique_question_text_sections(data),
        format_matching_pairs(data.get("matching_pairs", [])),
        format_correct_answers(data.get("correct_answers", [])),
        format_images(data.get("images", [])),
        format_list("Hints", data.get("hints", [])),
        format_list("Feedback", data.get("feedback", [])),
        "Task: classify this matching question. Return JSON only."
    ]

    return compact_join(sections)
