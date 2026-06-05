from bs4 import BeautifulSoup
import urllib.parse
from lxml import etree
import html
import re

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


def sanitize_mathml(mathml: str) -> str:

    mathml = html.unescape(mathml)

    mathml = re.sub(
        r"<mo><</mo>",
        "<mo>&lt;</mo>",
        mathml
    )

    mathml = re.sub(
        r"<mo>></mo>",
        "<mo>&gt;</mo>",
        mathml
    )

    return mathml


def node_to_latex(node):

    tag = etree.QName(node).localname

    if tag == "math":
        return "".join(node_to_latex(c) for c in node)

    if tag == "mrow":
        return "".join(node_to_latex(c) for c in node)

    if tag == "mn":
        return (node.text or "").strip()

    if tag == "mi":

        value = (node.text or "").strip()

        if value in GREEK_MAP:
            return GREEK_MAP[value]

        return value

    if tag == "mo":

        value = (node.text or "").strip()

        mapping = {
            "<": "<",
            ">": ">",
            "≤": r"\le",
            "≥": r"\ge",
            "≠": r"\ne",
            "±": r"\pm",
            "×": r"\times",
            "÷": r"\div",
            "∞": r"\infty",
            "=": "=",
            "+": "+",
            "-": "-",
        }

        return mapping.get(value, value)

    if tag == "mtext":
        return f" {(node.text or '').strip()} "

    if tag == "mfrac":
        return (
            r"\frac{"
            + node_to_latex(node[0])
            + "}{"
            + node_to_latex(node[1])
            + "}"
        )

    if tag == "msqrt":
        return (
            r"\sqrt{"
            + node_to_latex(node[0])
            + "}"
        )

    if tag == "mroot":
        return (
            r"\sqrt["
            + node_to_latex(node[1])
            + "]{"
            + node_to_latex(node[0])
            + "}"
        )

    if tag == "msup":
        return (
            node_to_latex(node[0])
            + "^{"
            + node_to_latex(node[1])
            + "}"
        )

    if tag == "msub":
        return (
            node_to_latex(node[0])
            + "_{"
            + node_to_latex(node[1])
            + "}"
        )

    if tag == "msubsup":
        return (
            node_to_latex(node[0])
            + "_{"
            + node_to_latex(node[1])
            + "}^{"
            + node_to_latex(node[2])
            + "}"
        )

    if tag == "mfenced":

        open_char = node.attrib.get("open", "(")
        close_char = node.attrib.get("close", ")")

        content = "".join(
            node_to_latex(c)
            for c in node
        )

        return f"{open_char}{content}{close_char}"

    if tag == "mover":
        return (
            r"\overset{"
            + node_to_latex(node[1])
            + "}{"
            + node_to_latex(node[0])
            + "}"
        )

    if tag == "munder":
        return (
            r"\underset{"
            + node_to_latex(node[1])
            + "}{"
            + node_to_latex(node[0])
            + "}"
        )

    if tag == "munderover":
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
        node_to_latex(c)
        for c in node
    )


def mathml_to_latex(mathml):

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

        latex = node_to_latex(root)

        latex = re.sub(
            r"\s+",
            " ",
            latex
        ).strip()

        return latex

    except Exception as ex:

        print("\n======================")
        print("FAILED MATHML")
        print(mathml)
        print("======================")
        print(ex)

        return ""
# ============================================================
# Extract MathML from SVG comment
# ============================================================

def extract_mathml_from_svg(src):
    try:
        decoded = urllib.parse.unquote(src)

        match = re.search(
            r'<!--MathML:\s*(.*?)-->',
            decoded,
            re.DOTALL
        )

        if match:
            return match.group(1).strip()

    except Exception as ex:
        print(f"[SVG Extraction Error] {ex}")

    return ""

# ============================================================
# Extract MathML from SVG comment
# ============================================================

def extract_mathml_from_svg(src):
    try:
        decoded = urllib.parse.unquote(src)

        match = re.search(
            r'<!--MathML:\s*(.*?)-->',
            decoded,
            re.DOTALL
        )

        if match:
            return match.group(1).strip()

    except Exception as ex:
        print(f"[SVG Extraction Error] {ex}")

    return ""


# ============================================================
# Main HTML Parser
# ============================================================

def parse_html_content(html_content):

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

        # ----------------------------------------------------
        # Priority 1 : data-latex
        # ----------------------------------------------------

        if img.get("data-latex"):

            latex = img.get(
                "data-latex",
                ""
            ).strip()

        # ----------------------------------------------------
        # Priority 2 : data-mathml
        # ----------------------------------------------------

        if not latex and img.get("data-mathml"):

            try:

                mathml = (
                    img.get("data-mathml", "")
                    .replace("«", "<")
                    .replace("»", ">")
                    .replace("¨", '"')
                    .replace("§", "&")
                )

                latex = mathml_to_latex(mathml)

            except Exception as ex:

                print(
                    f"[data-mathml conversion failed] {ex}"
                )

        # ----------------------------------------------------
        # Priority 3 : SVG embedded MathML
        # ----------------------------------------------------

        if not latex:

            mathml = extract_mathml_from_svg(src)

            if mathml:

                latex = mathml_to_latex(mathml)

        # ----------------------------------------------------
        # Priority 4 : alt fallback
        # ----------------------------------------------------

        if not latex:

            latex = img.get("alt", "").strip()

            if latex:

                print(
                    f"[ALT FALLBACK USED] {latex}"
                )

        if latex:

            img.replace_with(
                f"\\({latex}\\)"
            )

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

    remaining_html = str(soup).strip()

    if remaining_html:

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
                "audio": {
                    "url": src
                }
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
                "video": {
                    "url": src
                }
            })

    return contents