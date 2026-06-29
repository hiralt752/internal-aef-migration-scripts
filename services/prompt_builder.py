from prompts.base_prompt import BASE_CLASSIFICATION_PROMPT
from prompts.bloom_rules import BLOOM_RULES
from prompts.difficulty_rules import DIFFICULTY_RULES
from prompts.dok_rules import DOK_RULES, ISLAMIC_DOK_RULES
from prompts.output_schema import (
    MATH_SCIENCE_OUTPUT_SCHEMA,
    GENERAL_OUTPUT_SCHEMA,
    ISLAMIC_OUTPUT_SCHEMA,
    BLOOM_ONLY_OUTPUT_SCHEMA
)

from prompts.templates.multiple_choice import build_multiple_choice_prompt
from prompts.templates.fill_in_the_blank import build_fill_in_the_blank_prompt
from prompts.templates.dropdown import build_dropdown_prompt
from prompts.templates.dnd import build_dnd_prompt
from prompts.templates.matching import build_matching_prompt
from prompts.templates.generic import build_generic_prompt


CURRICULUM_SUBJECTS = {
    "SCIENCE",
    "SCIENCE_EN",
    "BIOLOGY",
    "BIOLOGY_EN",
    "CHEMISTRY",
    "CHEMISTRY_EN",
    "PHYSICS",
    "PHYSICS_EN"
}


ISLAMIC_SUBJECTS = {
    "ISLAMIC",
    "ISLAMIC_STUDIES"
}


BLOOM_ONLY_SUBJECTS = {
    "ARABIC",
    "SOCIAL",
    "SOCIAL_STUDIES"
}


TEMPLATE_MAP = {
    "MULTIPLE_CHOICE": build_multiple_choice_prompt,
    "MULTIPLE_SELECTION": build_multiple_choice_prompt,
    "FILL_IN_THE_BLANK": build_fill_in_the_blank_prompt,
    "FILL_IN_THE_BLANK_DRAG_DROP": build_dnd_prompt,
    "DROPDOWN": build_dropdown_prompt,
    "SELECT_A_BLANK": build_dropdown_prompt,
    "DND": build_dnd_prompt,
    "IMAGE_LABELLING_DRAG_DROP": build_dnd_prompt,
    "MATCHING": build_matching_prompt
}


def get_output_schema(folder_subject):
    folder_subject = str(
        folder_subject or ""
    ).strip().upper()

    if folder_subject in CURRICULUM_SUBJECTS:
        return MATH_SCIENCE_OUTPUT_SCHEMA

    if folder_subject in ISLAMIC_SUBJECTS:
        return ISLAMIC_OUTPUT_SCHEMA

    if folder_subject in BLOOM_ONLY_SUBJECTS:
        return BLOOM_ONLY_OUTPUT_SCHEMA

    return GENERAL_OUTPUT_SCHEMA


def get_dok_rules(folder_subject):
    folder_subject = str(
        folder_subject or ""
    ).strip().upper()

    if folder_subject in BLOOM_ONLY_SUBJECTS:
        return None

    if folder_subject in ISLAMIC_SUBJECTS:
        return ISLAMIC_DOK_RULES

    return DOK_RULES


def build_prompt(data):
    folder_subject = str(
        data.get("folder_subject", "")
    ).strip().upper()

    question_prompt = build_question_prompt(
        data
    )

    prompt_parts = [
        BASE_CLASSIFICATION_PROMPT.strip(),
        BLOOM_RULES.strip(),
        DIFFICULTY_RULES.strip()
    ]

    dok_rules = get_dok_rules(
        folder_subject
    )

    if dok_rules:
        prompt_parts.append(
            dok_rules.strip()
        )

    prompt_parts.extend(
        [
            get_output_schema(folder_subject).strip(),
            question_prompt.strip()
        ]
    )

    final_prompt = "\n\n".join(
        prompt_parts
    )

    return final_prompt


def build_question_prompt(data):
    question_type = str(
        data.get("question_type", "")
    ).strip().upper()

    template_builder = TEMPLATE_MAP.get(
        question_type,
        build_generic_prompt
    )

    return template_builder(
        data
    )
