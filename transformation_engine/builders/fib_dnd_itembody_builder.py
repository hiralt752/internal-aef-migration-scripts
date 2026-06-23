from bs4 import BeautifulSoup
from parsers.content_parser import parse_html_content
import re
from helpers.span_remover import remove_span_texts_from_html


def replace_blank_fields(html):
    """Replace <blank-field> tags with @_@ placeholder."""

    if not html:
        return ""

    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    for blank in soup.find_all(
        "blank-field"
    ):
        blank.replace_with("@_@")

    return str(soup)


def html_to_text(html):
    """Strip HTML to plain text."""

    if not html:
        return ""

    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    return soup.get_text(
        " ",
        strip=True
    )


def normalize_weight(weight):

    return round(
        weight / 100,
        4
    )


def _is_math_image(img):
    """Return True if the <img> represents a MathML / WIRIS / SVG equation."""
    import urllib.parse

    # Class-based detection (Wirisformula)
    classes = img.get("class") or []
    if "Wirisformula" in classes:
        return True

 

    # Has explicit MathML data attribute
    if img.get("data-mathml"):
        return True

    src = img.get("src", "")

    # Any data:image/ URI is an inline-rendered equation, not a content image
    if src.startswith("data:image/"):
        return True

    # SVG content markers (check decoded src for MathML / WIRIS indicators)
    if src.startswith("data:image/svg+xml"):
        decoded = urllib.parse.unquote(src).lower()
        if any(marker in decoded for marker in ("mathml", "wiris", "wrs:", "<math")):
            return True

    return False


def _extract_side_image_from_prompt(html):
    """Detect first non-math image in HTML or plain URL and return cleaned HTML + sideImage dict."""
    if not html:
        return html, None

    # Parse HTML — find the first <img> that is NOT a math equation
    soup = BeautifulSoup(html, "html.parser")
    for img in soup.find_all("img"):
        if _is_math_image(img):
            continue  # leave math images for parse_html_content() → LaTeX conversion
        src = img.get("src")
        if src:
            img.decompose()
            cleaned = str(soup).strip()
            return cleaned, {"url": src}

    # No non-math <img> tag found — look for bare image URLs (absolute or relative paths)
    # Match common image file extensions
    m = re.search(r"(https?:\\/\\/[^\"'\s>]+\\.(?:png|jpe?g|gif|svg)(?:\?[^\s\"'>]+)?)", html, re.IGNORECASE)
    if not m:
        # also match relative paths like ../path/foo.png or ./images/foo.jpg
        m = re.search(r"([\w\.\-\/_]+\\.(?:png|jpe?g|gif|svg)(?:\?[^\s\"'>]+)?)", html, re.IGNORECASE)

    if m:
        url = m.group(1)
        # remove the first occurrence of this url from html
        cleaned = html.replace(url, "").strip()
        return cleaned, {"url": url}

    return html, None


def build_fib_dnd_item_body(raw, question_id, lesson,file_path=None):

    body = raw.get("body", {})

    choices = body.get("choices", {})

    prompt = body.get("prompt")
    replaced = replace_blank_fields(prompt)
    cleaned_prompt, side_image = _extract_side_image_from_prompt(replaced)

    prompt = remove_span_texts_from_html(prompt, question_id, lesson, file_path)

    parsed_content = parse_html_content(
        cleaned_prompt,
        question_id,
        lesson
    )

    # keep first content item as sentence (fallback to text if parser returned empty)
    if parsed_content:
        sentence_val = parsed_content[0]
    else:
        sentence_val = {"type": "text", "text": html_to_text(cleaned_prompt)}

    return {

        "version": "1.0",

        "title": None,

        "subTitle": None,

        "instruction": None,

        "audio": None,

        "video": None,

        "image": None,

        "backgroundLayout": None,

        "timeSpentConfig": None,

        "splitContent": None,

        "sideImage": side_image,

        "showDragHandle":
            choices.get(
                "showDragHandle",
                True
            ),

        "shuffled":
            choices.get(
                "shuffle",
                True
            ),

        "optionsStyle": "option-style-1",

        "dropLimit": 1,

        "optionsPosition": "bottom",

        "statement": None,

        "sentence": sentence_val,

        "targets":
            build_fib_targets(
                body.get("blanks", [])
            ),

        "options":
            build_fib_options(
                choices.get(
                    "choiceItems",
                    []
                ), question_id, lesson
            )
    }


def build_fib_targets(blanks):

    targets = []

    for index, blank in enumerate(
        blanks,
        start=1
    ):

        targets.append({

            "id": index,

            "weight":
                normalize_weight(
                    blank.get(
                        "weight",
                        100
                    )
                ),

            "swappable": False,

            "swapGroupId": 0,

            "position": None
        })

    if targets:
        total_weight = sum(t["weight"] for t in targets)
        if total_weight > 0 and round(total_weight, 4) != 1.0:
            diff = 1.0 - total_weight
            targets[0]["weight"] = round(targets[0]["weight"] + diff, 4)

    return targets


def build_fib_options(choice_items, question_id, lesson):

    options = []

    for index, choice in enumerate(choice_items, start=1):

        parsed_content = parse_html_content(
            choice.get("value", ""),
            question_id,
            lesson
        )

        text = ""

        for item in parsed_content:

            if item.get("type") == "text":
                text += item.get("text", "")

        options.append({
            "id": index,
            "content": {
                "type": "text",
                "text": text
            }
        })

    return options
 