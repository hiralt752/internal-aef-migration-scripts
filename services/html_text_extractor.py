import re
import html
from bs4 import BeautifulSoup


def html_to_text(value):
    if value is None:
        return ""

    value = str(value)

    if not value.strip():
        return ""

    value = html.unescape(value)

    soup = BeautifulSoup(
        value,
        "html.parser"
    )

    for tag in soup.find_all(
        ["script", "style"]
    ):
        tag.decompose()

    for br in soup.find_all("br"):
        br.replace_with("\n")

    text = soup.get_text(
        " ",
        strip=True
    )

    text = text.replace(
        "\xa0",
        " "
    )

    text = re.sub(
        r"\s+",
        " ",
        text
    ).strip()

    return text


def extract_text_from_content(content):
    texts = []

    if not content:
        return texts

    if isinstance(content, dict):
        text = content.get("text")

        if text:
            clean_text = html_to_text(text)

            if clean_text:
                texts.append(clean_text)

        return texts

    if isinstance(content, list):
        for item in content:
            if not isinstance(item, dict):
                continue

            text = item.get("text")

            if text:
                clean_text = html_to_text(text)

                if clean_text:
                    texts.append(clean_text)

        return texts

    if isinstance(content, str):
        clean_text = html_to_text(content)

        if clean_text:
            texts.append(clean_text)

    return texts


def remove_duplicates(values):
    seen = set()
    result = []

    for value in values:
        value = str(value).strip()

        if not value:
            continue

        if value in seen:
            continue

        seen.add(value)
        result.append(value)

    return result


def collect_feedback_texts(question):
    feedback = []

    outcome = question.get(
        "outcomeDeclaration",
        {}
    )

    see_why = outcome.get(
        "seeWhy",
        {}
    )

    feedback.extend(
        extract_text_from_content(
            see_why.get("content")
        )
    )

    feedback_obj = outcome.get(
        "feedback",
        {}
    )

    if isinstance(feedback_obj, dict):
        for value in feedback_obj.values():
            if isinstance(value, dict):
                feedback.extend(
                    extract_text_from_content(
                        value.get("content")
                    )
                )

            elif isinstance(value, list):
                feedback.extend(
                    extract_text_from_content(value)
                )

            elif isinstance(value, str):
                clean_text = html_to_text(value)

                if clean_text:
                    feedback.append(clean_text)

    item_body = question.get(
        "itemBody",
        {}
    )

    options = item_body.get(
        "options",
        []
    )

    if isinstance(options, list):
        for option in options:
            if not isinstance(option, dict):
                continue

            option_feedback = option.get("feedback")

            if isinstance(option_feedback, str):
                clean_text = html_to_text(
                    option_feedback
                )

                if clean_text:
                    feedback.append(clean_text)

            elif isinstance(option_feedback, dict):
                feedback.extend(
                    extract_text_from_content(
                        option_feedback.get("content")
                    )
                )

    return remove_duplicates(feedback)


def collect_hint_texts(question):
    hints = []

    modal_feedback = question.get(
        "modalFeedback",
        {}
    )

    need_help = modal_feedback.get(
        "needHelp",
        {}
    )

    content_wrapper = need_help.get(
        "content",
        {}
    )

    if isinstance(content_wrapper, dict):
        hints.extend(
            extract_text_from_content(
                content_wrapper.get("content")
            )
        )

    return remove_duplicates(hints)