from bs4 import BeautifulSoup, NavigableString
import urllib.parse
from lxml import etree
import html
import re
from helpers.debug_logger import DebugLogger

logger = DebugLogger()
GREEK_MAP = {
    "α": r"\alpha",
    "β": r"\beta",
    "γ": r"\gamma",
    "δ": r"\delta",
    "ε": r"\varepsilon",
    "θ": r"\theta",
    "λ": r"\lambda",
    "μ": r"\mu",
    "π": r"\pi",
    "σ": r"\sigma",
    "φ": r"\phi",
    "ω": r"\omega",
}

ALLOWED_TAGS = {
    "ol", "li", "br", "table", "thead", "tbody", "tr", "td", "th",
    "b", "i", "u", "em", "strong", "p", "ul", "span",
}


LATEX_TEXT_ESCAPE_MAP = {
    "\\": r"\textbackslash{}",
    "{": r"\{",
    "}": r"\}",
    "$": r"\$",
    "&": r"\&",
    "#": r"\#",
    "%": r"\%",
    "_": r"\_",
}

# Commands that must be explicitly terminated before an alphabetic token.
# This repairs malformed values such as \timesh, \divx and \pir without
# changing structural commands such as \frac, \sqrt, \text, etc.
BOUNDARY_SENSITIVE_COMMANDS = (
    "times", "div", "cdot", "ast", "pm", "mp",
    "le", "ge", "ne", "neq", "approx", "equiv", "propto",
    "infty", "pi", "theta", "alpha", "beta", "gamma", "delta",
    "lambda", "mu", "sigma", "phi", "omega",
)


def escape_latex_text(value: str) -> str:
    return "".join(LATEX_TEXT_ESCAPE_MAP.get(char, char) for char in (value or ""))


def strip_math_delimiters(value: str) -> str:
    """Remove existing inline/display wrappers so the caller wraps exactly once."""
    value = (value or "").strip()

    # Some source fields contain doubled slashes before delimiters. Normalize
    # only delimiter slashes; never collapse backslashes globally.
    value = re.sub(r"\\\\(?=[()\[\]])", r"\\", value)

    changed = True
    while changed and value:
        changed = False
        wrappers = (
            (r"\(", r"\)"),
            (r"\[", r"\]"),
            ("$$", "$$"),
            ("$", "$"),
        )
        for opening, closing in wrappers:
            if value.startswith(opening) and value.endswith(closing):
                value = value[len(opening):-len(closing)].strip()
                changed = True
                break

    return value


def repair_latex_command_boundaries(value: str) -> str:
    if not value:
        return ""

    commands = "|".join(
        sorted(BOUNDARY_SENSITIVE_COMMANDS, key=len, reverse=True)
    )

    # \timesh -> \times{}h, \divx -> \div{}x, \pir -> \pi{}r
    return re.sub(
        rf"\\({commands})(?=[A-Za-z])",
        r"\\\1{}",
        value,
    )


def clean_existing_latex(value: str) -> str:
    value = html.unescape(value or "")
    value = strip_math_delimiters(value)
    value = repair_latex_command_boundaries(value)
    return value.strip()

def has_meaningful_html(html_content: str) -> bool:
    soup = BeautifulSoup(html_content or "", "html.parser")

    # Remove empty tags repeatedly, including nested empty tags
    for tag in soup.find_all():
        # Ignore <br> as meaningful content
        if tag.name == "br":
            tag.decompose()
            continue

        # If tag has no text and no meaningful child, remove it
        if not tag.get_text(strip=True) and not tag.find():
            tag.decompose()

    # Check again after removing empty tags
    return bool(soup.get_text(strip=True))

def normalize_math_words(latex: str) -> str:
    if not latex:
        return ""

    # MathJax ignores normal spaces in math mode.
    # So "x or x" must become "x\text{ or }x".
    latex = re.sub(
        r"(?<!\\text\{\s)\bor\b(?!\s*\})",
        r"\\text{ or }",
        latex
    )

    return latex

def strip_disallowed_tags(html_content, question_id=None, lesson=None):
    soup = BeautifulSoup(html_content, "html.parser")

    for tag in soup.find_all():
        if tag.name not in ALLOWED_TAGS:
            logger.log(
                question_id=question_id,
                lesson=lesson,
                question_type="HTML_SANITIZER",
                reason=f"Removed tag: <{tag.name}>",
                file_path=None
            )
            tag.unwrap()

    return str(soup)


def sanitize_mathml(mathml: str) -> str:
    # Do not html.unescape the complete XML before parsing. Doing so can turn
    # valid entities such as &lt; into raw XML markup and corrupt the tree.
    mathml = mathml or ""

    # Protect malformed raw comparison operators when they occur in <mo>.
    mathml = re.sub(r"<mo>\s*<\s*</mo>", "<mo>&lt;</mo>", mathml)
    mathml = re.sub(r"<mo>\s*>\s*</mo>", "<mo>&gt;</mo>", mathml)

    return mathml


def decode_wiris_mathml(mathml: str) -> str:
    return (
        (mathml or "")
        .replace("«", "<")
        .replace("»", ">")
        .replace("¨", '"')
        .replace("§", "&")
    )


def has_children(node, expected):
    return len(node) >= expected


def normalize_latex_for_preview(latex: str) -> str:
    if not latex:
        return ""

    latex = clean_existing_latex(latex)

    # Normalize ordinary whitespace only. TeX command boundaries are protected
    # by explicit empty groups such as \times{}h and \div{}x.
    latex = re.sub(r"(\\\ ){2,}", r"\\ ", latex)
    latex = re.sub(r"(?<!\\) {2,}", " ", latex)
    latex = re.sub(r"\s*([<>])\s*", r" \1 ", latex)

    latex = latex.replace(r"\left\{ ", r"\left\{")
    latex = latex.replace(r" \right\}", r"\right\}")
    latex = repair_latex_command_boundaries(latex)

    return latex.strip()


def node_to_latex(node):

    tag = etree.QName(node).localname

    if tag in {"math", "mrow"}:
        return "".join(node_to_latex(c) + (c.tail or "") for c in node)

    if tag == "mn":
        return (node.text or "").strip()


    if tag == "mi":
        value = (node.text or "").strip()

        if not value:
            return ""

        if value in GREEK_MAP:
            # Braces terminate the command before any following identifier.
            return f"{{{GREEK_MAP[value]}}}"

        if len(value) > 1:
            return rf"\text{{{escape_latex_text(value)}}}"

        return value

    if tag == "mo":
        raw = html.unescape(node.text or "")

        if raw in {" ", "\u00a0"}:
            return " "

        value = raw.strip()

        if not value:
            return " "

        mapping = {
            "<": " < ",
            ">": " > ",
            "≤": r"\le{}",
            "≥": r"\ge{}",
            "≠": r"\ne{}",
            "±": r"\pm{}",
            "×": r"\times{}",
            "÷": r"\div{}",
            "⋅": r"\cdot{}",
            "·": r"\cdot{}",
            "∞": r"\infty{}",
            "−": "-",
            "=": " = ",
            "+": "+",
            "-": "-",
            "\u00a0": " ",
            "{": r"\left\{",
            "}": r"\right\}",
            "|": r"\mid ",
            "(": "(",
            ")": ")",
            ".": ".",
            ",": ",",
        }

        return mapping.get(value, value)

    if tag == "mtext":
        text = (node.text or " ").strip()
        if not text:
            return " "
        return rf" \text{{{escape_latex_text(text)}}} "

    if tag == "mspace":
        if node.attrib.get("linebreak") == "newline":
            return "\\\\ "
        return " "

    if tag == "mfrac":

        if not has_children(node, 2):

            logger.log(
                question_id=None,
                lesson=None,
                question_type="MATHML",
                reason=f"Invalid mfrac: expected 2 children got {len(node)}",
                file_path=None
            )

            return "".join(
                node_to_latex(c)
                for c in node
            )

        return (
            r"\frac{"
            + node_to_latex(node[0])
            + (node[0].tail or "")
            + "}{"
            + node_to_latex(node[1])
            + (node[1].tail or "")
            + "}"
        )

    if tag == "msqrt":

        if not has_children(node, 1):

            logger.log(
                question_id=None,
                lesson=None,
                question_type="MATHML",
                reason="Invalid msqrt: no children",
                file_path=None
            )

            return r"\sqrt{}"

        return (
            r"\sqrt{"
            + "".join(node_to_latex(c) + (c.tail or "") for c in node)
            + "}"
        )

    if tag == "mroot":

        if len(node) < 2:

            logger.log(
                question_id=None,
                lesson=None,
                question_type="MATHML",
                reason=f"Invalid mroot: expected 2 children got {len(node)}",
                file_path=None
            )

            return "".join(
                node_to_latex(c)
                for c in node
            )

        return (
            r"\sqrt["
            + node_to_latex(node[1])
            + (node[1].tail or "")
            + "]{"
            + node_to_latex(node[0])
            + (node[0].tail or "")
            + "}"
        )

    if tag == "msup":

        if not has_children(node, 2):

            logger.log(
                question_id=None,
                lesson=None,
                question_type="MATHML",
                reason=f"Invalid msup: expected 2 children got {len(node)}",
                file_path=None
            )

            return "".join(
                node_to_latex(c) + (c.tail or "")
                for c in node
            )

        return (
            node_to_latex(node[0]) + (node[0].tail or "")
            + "^{"
            + node_to_latex(node[1]) + (node[1].tail or "")
            + "}"
        )

    if tag == "msub":

        if len(node) < 2:

            logger.log(
                question_id=None,
                lesson=None,
                question_type="MATHML",
                reason=f"Invalid msub: expected 2 children got {len(node)}",
                file_path=None
            )

            return "".join(
                node_to_latex(c) + (c.tail or "")
                for c in node
            )

        return (
            node_to_latex(node[0]) + (node[0].tail or "")
            + "_{"
            + node_to_latex(node[1]) + (node[1].tail or "")
            + "}"
        )

    if tag == "msubsup":

        if len(node) < 3:

            logger.log(
                question_id=None,
                lesson=None,
                question_type="MATHML",
                reason=f"Invalid msubsup: expected 3 children got {len(node)}",
                file_path=None
            )

            return "".join(
                node_to_latex(c)
                for c in node
            )

        return (
            node_to_latex(node[0]) + (node[0].tail or "")
            + "_{"
            + node_to_latex(node[1]) + (node[1].tail or "")
            + "}^{"
            + node_to_latex(node[2]) + (node[2].tail or "")
            + "}"
        )

    if tag == "mfenced":

        open_char = node.attrib.get("open", "(")
        close_char = node.attrib.get("close", ")")

        content = "".join(
            node_to_latex(c) + (c.tail or "")
            for c in node
        )

        return f"{open_char}{content}{close_char}"

    if tag == "mover":

        if len(node) < 2:

            logger.log(
                question_id=None,
                lesson=None,
                question_type="MATHML",
                reason=f"Invalid mover: expected 2 children got {len(node)}",
                file_path=None
            )

            return "".join(
                node_to_latex(c)
                for c in node
            )

        return (
            r"\overset{"
            + node_to_latex(node[1])
            + "}{"
            + node_to_latex(node[0])
            + "}"
        )

    if tag == "munder":

        if not has_children(node, 2):

            logger.log(
                question_id=None,
                lesson=None,
                question_type="MATHML",
                reason=f"Invalid munder: expected 2 children got {len(node)}",
                file_path=None
            )

            return "".join(
                node_to_latex(c)
                for c in node
            )

        return (
            r"\underset{"
            + node_to_latex(node[1]) + (node[1].tail or "")
            + "}{"
            + node_to_latex(node[0]) + (node[0].tail or "")
            + "}"
        )

    if tag == "munderover":
        if len(node) < 3:

            logger.log(
                question_id=None,
                lesson=None,
                question_type="MATHML",
                reason=f"Invalid munderover: expected 3 children got {len(node)}",
                file_path=None
            )

            return "".join(
                node_to_latex(c)
                for c in node
            )

        return (
            r"\overset{"
            + node_to_latex(node[2])
            + "}{\\underset{"
            + node_to_latex(node[1])
            + "}{"
            + node_to_latex(node[0])
            + "}}"
        )

    return "".join(
        node_to_latex(c) + (c.tail or "")
        for c in node
    )


def mathml_to_latex(mathml,question_id,lesson):

    try:

        mathml = sanitize_mathml(mathml)

        parser = etree.XMLParser(
            recover=True,
            remove_blank_text=True
        )

        root = etree.fromstring(
            mathml.encode("utf-8"),
            parser
        )

        if root is None:
            raise ValueError("MathML parsing produced no root element")

        latex = node_to_latex(root)
        latex = repair_latex_command_boundaries(latex)

        # Preserve existing support for old "\ or\" style output.
        latex = re.sub(r"\\\s*or\\?", r"\\text{ or }", latex)

        latex = normalize_latex_for_preview(latex)
        latex = normalize_math_words(latex)
        return latex

    except Exception as ex:

        print("\n======================")
        print("FAILED MATHML")
        print(mathml)
        print("======================")
        print(ex)
        if logger:
            logger.log(
                question_id=question_id,
                lesson=lesson,
                question_type="MATHML",
                reason=str(ex),
                file_path=None
            )
        return ""


def extract_mathml_from_svg(src):
    try:
        decoded = urllib.parse.unquote(src)

        match = re.search(
            r"<!--MathML:\s*(.*?)-->",
            decoded,
            re.DOTALL
        )

        if match:
            return match.group(1).strip()

    except Exception as ex:
        print(f"[SVG Extraction Error] {ex}")

    return ""


def parse_html_content(html_content,question_id,lesson):
    soup = BeautifulSoup(
        html_content or "",
        "html.parser"
    )

    contents = []

    # ========================================================
    # Process Wiris formulas
    # ========================================================

    for img in soup.find_all("img"):

        src = img.get("src", "")

        if not src:
            continue

        is_wiris = (
            "Wirisformula" in (img.get("class") or [])
            or (
                src.startswith("data:image/svg+xml")
                and "mathml" in urllib.parse.unquote(src).lower()
            )
        )

        if not is_wiris:
            continue

        latex = ""

        # Prefer MathML because some legacy data-latex values contain already
        # wrapped delimiters or merged commands such as \timesh and \divx.
        if img.get("data-mathml"):
            try:
                mathml = decode_wiris_mathml(
                    img.get("data-mathml", "")
                )
                latex = mathml_to_latex(mathml, question_id, lesson)
            except Exception as ex:
                print(f"[data-mathml conversion failed] {ex}")
                logger.log(
                    question_id=question_id,
                    lesson=lesson,
                    question_type="MATHML",
                    reason=f"[data-mathml conversion failed] {ex}",
                    file_path=None
                )

        if not latex:
            mathml = extract_mathml_from_svg(src)
            if mathml:
                latex = mathml_to_latex(mathml, question_id, lesson)

        if not latex and img.get("data-latex"):
            latex = clean_existing_latex(img.get("data-latex", ""))

        if not latex:
            latex = clean_existing_latex(img.get("alt", ""))
            if logger:
                logger.log(
                    question_id=question_id,
                    lesson=lesson,
                    question_type="MATHML",
                    reason=f"[ALT FALLBACK USED] {latex}",
                    file_path=None
                )
            if latex:
                print(f"[ALT FALLBACK USED] {latex}")

        if latex:
            latex = normalize_latex_for_preview(latex)
            latex = normalize_math_words(latex)
            # Critical fix:
            # Use NavigableString so BeautifulSoup serializes raw < and >
            # as &lt; and &gt; in final HTML, while MathJax still receives
            # valid TeX when rendered.
            img.replace_with(NavigableString(f" \\({latex}\\) "))

    # ========================================================
    # Handle remaining images
    # ========================================================

    for img in soup.find_all("img"):

        src = img.get("src")

        if not src:
            continue

        contents.append({
            "type": "image",
            "image": {
                "url": src,
                "zoom": True
            }
        })

        img.decompose()

    # ========================================================
    # Remaining HTML
    # ========================================================

    sanitized_html = strip_disallowed_tags(
        str(soup),
        question_id,
        lesson
    )

    clean_soup = BeautifulSoup(sanitized_html, "html.parser")

    for tag in clean_soup.find_all():
        text = tag.get_text(strip=True)

        # If tag has no text and no meaningful child, remove it
        if not text and not tag.find():
            tag.decompose()

    remaining_html = re.sub(
        r">\s*\n\s*<",
        "><",
        str(clean_soup)
    ).strip()
    remaining_html = re.sub(r" {2,}", " ", remaining_html)

    # Final check: ignore if only empty HTML remains
    plain_text = BeautifulSoup(remaining_html, "html.parser").get_text(strip=True)

    if remaining_html and has_meaningful_html(remaining_html):
        contents.insert(0, {
            "type": "text",
            "text": remaining_html
        })

    # ========================================================
    # Audio
    # ========================================================

    for audio in soup.find_all("audio"):

        src = audio.get("src")

        if not src:
            source = audio.find("source")
            if source:
                src = source.get("src")

        if src:
            contents.append({
                "type": "audio",
                "audio": {"url": src}
            })

    # ========================================================
    # Video
    # ========================================================

    for video in soup.find_all("video"):

        src = video.get("src")

        if not src:
            source = video.find("source")
            if source:
                src = source.get("src")

        if src:
            contents.append({
                "type": "video",
                "video": {"url": src}
            })

    return contents