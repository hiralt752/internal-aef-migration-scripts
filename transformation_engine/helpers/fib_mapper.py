import re
from urllib.parse import unquote
from parsers.content_parser import parse_html_content, mathml_to_latex_auto
from bs4 import BeautifulSoup
from helpers.span_remover import remove_span_texts_from_html


def clean_latex_answer(latex_str):
    if not latex_str or not isinstance(latex_str, str):
        return latex_str or ""

    # Replace non-breaking spaces (U+00A0) with standard ASCII space
    latex_str = latex_str.replace("\u00a0", " ").replace("&nbsp;", " ")

    # Strip degree symbol ° / \u00b0 (server rejected 'circ' as unsupported construct)
    latex_str = latex_str.replace("°", "").replace("\u00b0", "")

    # Convert \left\vert / \right\vert / \vert to plain |
    latex_str = latex_str.replace(r"\left\vert", "|").replace(r"\right\vert", "|").replace(r"\vert", "|")

    # Strip \left and \right from fence delimiters
    latex_str = re.sub(r"\\left\s*([(\[|])", r"\1", latex_str)
    latex_str = re.sub(r"\\right\s*([)\]|])", r"\1", latex_str)

    # Remove empty trailing braces after LaTeX symbol commands
    symbol_commands = ["infty", "le", "ge", "times", "div", "pm", "cdot", "Delta", "pi", "alpha", "beta", "theta", "rightarrow", "leftarrow"]
    for cmd in symbol_commands:
        pattern = r"\\" + cmd + r"\{\}"
        repl = r"\\" + cmd + " "
        latex_str = re.sub(pattern, repl, latex_str)

    # Fix trig function exponent spacing: \cos ^{ -> \cos^{, \tan ^{ -> \tan^{
    latex_str = re.sub(r"\\(|tan|sin|csc|sec|cot)\s+\^{", r"\\\1^{", latex_str)

    # Strip unnecessary curly braces around single character/digit exponents and subscripts
    latex_str = re.sub(r"\^\{([a-zA-Z0-9])\}", r"^\1", latex_str)
    latex_str = re.sub(r"\_\{([a-zA-Z0-9])\}", r"_\1", latex_str)

    # Strip inline math delimiters \( and \) if present (rejected as unsupported construct '(' by API schema validation)
    if latex_str.startswith(r"\(") and latex_str.endswith(r"\)"):
        latex_str = latex_str[2:-2].strip()

    latex_str = latex_str.replace(r"\\", " ").strip()
    latex_str = re.sub(r"\s+", " ", latex_str).strip()

    return latex_str


def get_text_value(value) :
    if not value:
        return ""

    return value[0].get("text")


def extract_correct_answer_text(answer_html, question_id, lesson, wiris_xml=None):
    if (not answer_html or "<math" not in str(answer_html)) and wiris_xml:
        m = re.search(r"<math.*?</math>", str(wiris_xml), re.DOTALL)
        if m:
            answer_html = m.group(0)

    if not answer_html:
        return ""

    if "<math" in str(answer_html):
        latex = mathml_to_latex_auto(answer_html, question_id, lesson)
        if latex:
            return clean_latex_answer(latex)

    parsed_answer = parse_html_content(
        answer_html,
        question_id,
        lesson
    )

    text_value = get_text_value(parsed_answer)
    if text_value:
        return clean_latex_answer(text_value)

    fallback_text = BeautifulSoup(
        answer_html or "",
        "html.parser"
    ).get_text(" ", strip=True)
    if fallback_text:
        return clean_latex_answer(fallback_text)

    return clean_latex_answer(answer_html or "")

def get_list_of_text(value):
    return [v.get("text") for v in value]


def extract_feedback_text(feedback_html, question_id, lesson):
    # items[].feedback is a plain string field, not a ContentItem[] -
    # extract_table=False keeps any table inline instead of pulling it into
    # a separate item that the loop below would then drop.
    parsed_feedback = parse_html_content(
        feedback_html or "",
        question_id,
        lesson,
        extract_table=False
    )

    for item in parsed_feedback:
        if item.get("type") == "text" and item.get("text"):
            return item["text"]

    return ""


def build_answer_in_widget_format(
    correct_answer,
    question_id,
    lesson
):
    """Return the primary FIB answer in the API's accepted scalar format."""
    return extract_correct_answer_text(
        correct_answer,
        question_id,
        lesson
    )


def is_legacy_blank_marker(tag):
    """Return True for legacy WIRIS images that represent a FIB blank."""
    if tag.name != "img":
        return False

    marker_data = " ".join([
        tag.get("data-mathml", ""),
        tag.get("alt", ""),
        unquote(tag.get("src", ""))
    ])

    return bool(re.search(r"\bblank(?:\b|_)", marker_data, re.IGNORECASE))

def derive_latex_evaluation_settings(blank_data, wiris_xml, is_wiris=False):
    """
    Derives latexEvaluationSettings object for Math/WIRIS FIB items based on raw blank data
    and WIRIS XML assertions.
    """
    dec_notation = blank_data.get("decimalNotation") or "POINT"
    per_notation = blank_data.get("periodNotation") or "COMMA"

    math_comp = "MATHEMATICALLY_EQUAL"
    is_simplified = True if is_wiris else False
    is_factorized = True if is_wiris else False

    if wiris_xml and isinstance(wiris_xml, str):
        if "equivalent_literal" in wiris_xml:
            math_comp = "LITERALLY_EQUAL"
        elif "equivalent_equations" in wiris_xml:
            math_comp = "EQUIVALENT_EQUATIONS"

        if "check_simplified" in wiris_xml:
            is_simplified = True
        if "check_factorized" in wiris_xml:
            is_factorized = True

    return {
        "decimalNotation": dec_notation,
        "periodNotation": per_notation,
        "mathComparison": math_comp,
        "isExpressionSimplified": is_simplified,
        "isExpressionFactorized": is_factorized
    }

def map_fib_structure(raw, qid, lesson, file_path):
    body = raw.get("body", {})
    prompt = body.get("prompt", "")

    prompt = remove_span_texts_from_html(prompt, qid, lesson, file_path)

    soup = BeautifulSoup(
        prompt,
        "html.parser"
    )

    blanks = body.get(
        "blanks",
        []
    )

    blank_lookup = {
        int(x.get("id")): x
        for x in blanks
    }

    validation_lookup = {}
    answer_mapping = (
        raw.get("validation", {})
        .get("validResponse", {})
        .get("answerMapping", [])
    )

    for answer in answer_mapping:
        validation_lookup[
            int(answer.get("blankId"))
        ] = answer

    sequential_id = 1
    items = []
    correct_answers = []

    blank_fields = soup.find_all("blank-field")
    if blank_fields:
        blank_sources = [
            (
                blank_lookup.get(int(blank.get("id")), {}),
                int(blank.get("id")),
                blank
            )
            for blank in blank_fields
        ]
    else:

        legacy_markers = [
            image
            for image in soup.find_all("img")
            if is_legacy_blank_marker(image)
        ]
        blank_sources = [
            (
                blank_data,
                int(blank_data.get("id")),
                legacy_markers[index] if index < len(legacy_markers) else None
            )
            for index, blank_data in enumerate(blanks)
        ]

    for blank_data, old_blank_id, blank_marker in blank_sources:

        validation_data = validation_lookup.get(
            old_blank_id,
            {}
        )

        correct_answer = (
            validation_data.get("correctAnswer")
            or validation_data.get("answer")
            or blank_data.get("answer")
            or blank_data.get("correctAnswer")
            or ""
        )

        alternate_answers = (
            validation_data.get(
                "alternateAnswers",
                []
            )
        )

        raw_wiris_xml = blank_data.get("wirisXml")
        raw_wiris_svg = blank_data.get("wirisSvg")

        wiris_xml = raw_wiris_xml.strip() if (isinstance(raw_wiris_xml, str) and raw_wiris_xml.strip()) else None
        wiris_svg = raw_wiris_svg.strip() if (isinstance(raw_wiris_svg, str) and raw_wiris_svg.strip()) else None

        has_wiris = bool(
            blank_data.get("wirisXml") and
            blank_data.get("wirisSvg")
        )
        is_math_blank = bool(wiris_xml or blank_data.get("type") == "MATH_BLANK" or "<math" in str(correct_answer))

        if has_wiris:
            input_type = "math"
            answer_type = "latex"
            latex_settings = derive_latex_evaluation_settings(blank_data, wiris_xml, is_wiris=True)
        elif is_math_blank:
            answer_type = "calculated"
            input_type = "math"
            latex_settings = derive_latex_evaluation_settings(blank_data, wiris_xml, is_wiris=True)
        else:
            answer_type = detect_answer_type(
                correct_answer
            )
            input_type = blank_data.get(
                "type",
                "TEXT_BLANK"
            )
            latex_settings = None

        feedback = blank_data.get("feedback") or ""
        parsed_feedback = extract_feedback_text(
            feedback,
            qid,
            lesson
        )

        item = {
            "id": sequential_id,
            "weight": normalize_weight(
                blank_data.get(
                    "weight",
                    100.0
                )
            ),
            "feedback": parsed_feedback,
            "rules": blank_data.get(
                "rules",
                []
            ),
            "latexEvaluationSettings": latex_settings,
            "answerType": answer_type,
            "inputType": input_type,
            "swappable": False,
            "swapGroupId": 0,
            "withBlankPicker": False,
            "allowEquivalentNumber": False,
            "simplestFormFraction": False,
            "decimals": None,
            "itemId": None,
            "position": None,
            "wirisXml": wiris_xml,
            "wirisSvg": wiris_svg
        }

        items.append(item)
        mapped_correct_answer = extract_correct_answer_text(
            correct_answer,
            qid,
            lesson,
            wiris_xml=wiris_xml
        )



        correct_answers.append({
            "blankId": sequential_id,
            "correctAnswer": mapped_correct_answer,
            "alternateAnswers": alternate_answers,
            "answerInWidgetFormat": mapped_correct_answer
        })

        if blank_marker is not None:
            blank_marker.replace_with("@_@")
        sequential_id += 1

    transformed_html = str(soup)

    return {
        "sentence_text": transformed_html,
        "items": items,
        "correct_answers": correct_answers,
        "multiple_answer": False
    }


def normalize_weight(weight):
    try:
        return float(weight) / 100
    except Exception:
        return 1.0


def detect_answer_type(answer):
    if answer is None:
        return "text"

    answer = str(answer).strip()
    if not answer:
        return "text"

    number_pattern = (
        r"^-?\d+(\.\d+)?$"
    )

    if re.fullmatch(
        number_pattern,
        answer
    ):
        return "number"

    formula_indicators = [
        "=",
        "\\frac",
        "\\sqrt",
        "^",
        "+"
    ]

    for token in formula_indicators:
        if token in answer:
            return "calculated"

    return "text"
