from bs4 import BeautifulSoup, NavigableString
import urllib.parse
from lxml import etree
import html
import re
from helpers.debug_logger import DebugLogger

logger = DebugLogger()
GREEK_MAP = {
    "\u03b1": r"\alpha",
    "\u03b2": r"\beta",
    "\u03b3": r"\gamma",
    "\u03b4": r"\delta",
    "\u03b5": r"\varepsilon",
    "\u03b8": r"\theta",
    "\u03bb": r"\lambda",
    "\u03bc": r"\mu",
    "\u03c0": r"\pi",
    "\u03c3": r"\sigma",
    "\u03c6": r"\phi",
    "\u03c9": r"\omega",
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

MATH_FUNCTIONS = {
    "sin", "cos", "tan", "cot", "sec", "csc",
    "arcsin", "arccos", "arctan", "arccot", "arcsec", "arccsc",
    "sinh", "cosh", "tanh", "coth", "sech", "csch",
    "log", "ln", "lg", "lim", "max", "min", "det", "dim", "gcd", "deg", "mod"
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
    "|": "|",
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

PROTECTED_LATEX_COMMANDS = {
    "left", "right", "frac", "sqrt", "text",
    "overset", "underset",
    "leq", "geq", "neq",
    "leftarrow", "rightarrow",
}


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

    commands = sorted(BOUNDARY_SENSITIVE_COMMANDS, key=len, reverse=True)
    protected_prefixes = sorted(PROTECTED_LATEX_COMMANDS, key=len, reverse=True)

    def repair_token(match):
        token = match.group(1)

        if token in PROTECTED_LATEX_COMMANDS:
            return "\\" + token

        # Never split structural commands such as \left, \right or \frac into
        # shorter operator commands. A previous broad prefix repair can turn
        # \left\{ into \le{}ft\{, which then renders as visible raw text.
        if any(token.startswith(command) for command in protected_prefixes):
            return "\\" + token

        # \timesh -> \times{}h, \divx -> \div{}x, \pir -> \pi{}r.
        # Match only complete alphabetic command tokens so \left is not
        # misread as \le + ft.
        for command in commands:
            if token.startswith(command) and token != command:
                return "\\" + command + "{}" + token[len(command):]

        return "\\" + token

    return re.sub(r"\\([A-Za-z]+)", repair_token, value)


def clean_existing_latex(value: str) -> str:
    value = html.unescape(value or "")
    value = strip_math_delimiters(value)
    value = re.sub(r"(^|\s)\\\\([A-Za-z]+)", r"\1\\\2", value)
    value = repair_latex_command_boundaries(value)
    value = repair_known_malformed_latex(value)
    return value.strip()


def repair_known_malformed_latex(value: str) -> str:
    if not value:
        return ""

    # Repair escaped curly braces around theta or variables: \{ \theta \} -> {\theta}
    value = re.sub(r"\\\{\s*\\?([a-zA-Z]+)\s*\\\}", r"{\\\1}", value)

    # Repair \text{sec}, \text{cot}, \text{sin}, etc. into standard \sec, \cot, \sin LaTeX commands
    value = re.sub(
        r"\\text\{\s*(sec|cot|sin|cos|tan|csc|log|ln|lim|max|min|deg)\s*\}",
        r"\\\1 ",
        value
    )

    # Repair legacy output where \left was accidentally split into
    # "\le{}ft" or "\le ft".
    value = re.sub(r"\\le\{\}\s*ft(?=\\|\b|\{)", r"\\left", value)
    value = re.sub(r"\\leq\{\}\s*ft(?=\\|\b|\{)", r"\\left", value)
    value = re.sub(r"\\le\s+ft(?=\\|\b|\{)", r"\\left", value)
    value = re.sub(r"\\le\{\}\s*ft\\\{", r"\\left\\{", value)
    value = re.sub(r"\\le\s*ft\\\{", r"\\left\\{", value)
    value = re.sub(r"\\le\{\}\s*ft", r"\\left", value)
    value = re.sub(r"\\le\s*ft", r"\\left", value)
    return value


def normalize_plain_latex_text(value: str) -> str:
    """Normalize LaTeX already present as text in source HTML.

    WIRIS images are converted separately, but some source prompts already
    contain TeX text such as "\\(...\\)" or unwrapped TeX commands.
    """
    if not value or "\\" not in value:
        return value or ""

    value = re.sub(r"\\\\(?=[()\[\]])", r"\\", value)
    value = repair_known_malformed_latex(value)

    def clean_inner(math_str):
        cleaned = strip_math_delimiters(math_str)
        cleaned = repair_known_malformed_latex(cleaned)
        cleaned = normalize_latex_for_preview(cleaned)
        return cleaned

    value = re.sub(r"\\\((.*?)\\\)", lambda m: r"\(" + clean_inner(m.group(1)) + r"\)", value, flags=re.DOTALL)
    value = re.sub(r"\\\[(.*?)\\\]", lambda m: r"\[" + clean_inner(m.group(1)) + r"\]", value, flags=re.DOTALL)

    # Split by existing \( ... \) and \[ ... \] blocks so we only auto-wrap outside chunks
    parts = re.split(r"(\\\(.*?\\\)|\\\[.*?\\\])", value, flags=re.DOTALL)
    processed = []

    # Match any unwrapped LaTeX command run (not a fixed whitelist, so
    # relational/operator commands such as \le, \ge, \neq are caught too,
    # not just the function-name commands below), including a leading
    # signed number glued directly onto the command (e.g. "-2\le x\le 5"
    # must wrap as a whole, not just from "\le" onward).
    unwrapped_pattern = re.compile(
        r"((?:[-+]?\d+(?:\.\d+)?\s*)?\\[A-Za-z]+\b[^\n<;]+?)"
        r"(?=\s*;\s*|\s+and\s+|\s+or\s+|<br|>|\.\s+|\s*$)"
    )

    for part in parts:
        if not part:
            continue
        if part.startswith(r"\(") or part.startswith(r"\["):
            processed.append(part)
        else:
            if "\\" in part:
                part = unwrapped_pattern.sub(
                    lambda m: r"\(" + clean_inner(m.group(1)) + r"\)",
                    part
                )
            processed.append(part)

    res = "".join(processed)
    while r"\(\(" in res:
        res = res.replace(r"\(\(", r"\(").replace(r"\)\)", r"\)")
    return res


def normalize_plain_latex_text_nodes(soup: BeautifulSoup) -> None:
    for text_node in list(soup.find_all(string=True)):
        text = str(text_node)
        if "\\" not in text:
            continue
        normalized_text = normalize_plain_latex_text(text)
        if normalized_text != text:
            text_node.replace_with(NavigableString(normalized_text))


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
    # So "x or x" must become "x\text{ or }x" and "x and x" -> "x\text{ and }x".
    print("before",latex)
    # latex = re.sub(
    #     r"(?<!\\text\{\s)\bor\b(?!\s*\})",
    #     r"\\text{ or }",
    #     latex
    # )
    latex = re.sub(r"\\le\{\}", r"\\le ", latex)
    print("after",latex)
    # latex = re.sub(
    #     r"(?<!\\text\{\s)\band\b(?!\s*\})",
    #     r"\\text{ and }",
    #     latex
    # )

    return latex


def convert_sup_sub_to_latex(soup: BeautifulSoup) -> None:
    """Flatten plain-text <sup>/<sub> into inline LaTeX (\\(^{..}\\) / \\(_{..}\\)).

    The delivery API rejects <sup>/<sub> outright ("contains disallowed
    tag"), so they cannot simply be added to ALLOWED_TAGS. A bare
    \\(^{23}\\) placed right after the preceding text renders as a normal
    superscript in MathJax with no tag needed, matching how the rest of this
    pipeline already emits math as \\( \\)-wrapped LaTeX instead of HTML.
    """
    for tag in soup.find_all(["sup", "sub"]):
        # A sup/sub wrapping structural markup (e.g. a FIB <blank-field>) is
        # not a plain exponent -- unwrap it so the nested element survives,
        # instead of flattening it away with get_text().
        if tag.find(True) is not None:
            tag.unwrap()
            continue

        inner = tag.get_text().replace(" ", " ").strip()

        if not inner:
            tag.unwrap()
            continue

        symbol = "^" if tag.name == "sup" else "_"
        tag.replace_with(
            NavigableString(rf"\({symbol}{{{escape_latex_text(inner)}}}\)")
        )


def strip_disallowed_tags(html_content, question_id=None, lesson=None):
    soup = BeautifulSoup(html_content, "html.parser")

    convert_sup_sub_to_latex(soup)

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


def _table_cell_content(cell, question_id, lesson):
    inner_html = cell.decode_contents()
    sanitized = strip_disallowed_tags(inner_html, question_id, lesson)
    sanitized = re.sub(r">\s*\n\s*<", "><", sanitized).strip()
    sanitized = re.sub(r" {2,}", " ", sanitized)
    return sanitized


def _table_row_cells(row, question_id, lesson):
    return [
        {"content": _table_cell_content(cell, question_id, lesson)}
        for cell in row.find_all(["td", "th"], recursive=False)
    ]


def _own_table_rows(table_tag):
    # Only rows that belong to this table, not to a table nested inside one
    # of its cells.
    return [
        tr for tr in table_tag.find_all("tr")
        if tr.find_parent("table") is table_tag
    ]


def parse_table_tag(table_tag, question_id, lesson):
    rows = _own_table_rows(table_tag)

    if not rows:
        return None

    # If any row uses <th>, that row is the header. Otherwise the source
    # table has no explicit header at all (the common case in migrated
    # data), so the first row is promoted to satisfy the schema's required
    # "th" while every other row becomes a body row.
    header_row = next((tr for tr in rows if tr.find("th")), rows[0])
    header_cells = _table_row_cells(header_row, question_id, lesson)

    if not header_cells:
        return None

    data_rows = []
    for tr in rows:
        if tr is header_row:
            continue
        cells = _table_row_cells(tr, question_id, lesson)
        if cells:
            data_rows.append({"td": cells})

    if not data_rows:
        logger.log(
            question_id=question_id,
            lesson=lesson,
            question_type="TABLE_PARSER",
            reason="Table has no body rows after header extraction; left as raw HTML",
            file_path=None
        )
        return None

    return {
        "th": {"td": header_cells},
        "tr": data_rows
    }


def extract_tables(soup, question_id, lesson):
    table_items = []
    tables = soup.find_all("table")
    outer_tables = [t for t in tables if t.find_parent("table") is None]

    for table_tag in outer_tables:
        table_obj = parse_table_tag(table_tag, question_id, lesson)

        if table_obj is None:
            continue

        table_items.append({
            "type": "table",
            "table": table_obj
        })
        table_tag.decompose()

    return table_items


def sanitize_mathml(mathml: str) -> str:
    # Do not html.unescape the complete XML before parsing. Doing so can turn
    # valid entities such as &lt; into raw XML markup and corrupt the tree.
    mathml = mathml or ""

    # Protect malformed raw comparison operators when they occur in <mo>.
    mathml = re.sub(r"<mo>\s*<\s*</mo>", "<mo>&lt;</mo>", mathml)
    mathml = re.sub(r"<mo>\s*>\s*</mo>", "<mo>&gt;</mo>", mathml)

    return mathml


def decode_wiris_mathml(mathml: str) -> str:
    mathml = mathml or ""

    # Historical WIRIS payloads use CP1252-ish placeholders for XML markup.
    mathml = (
        mathml
        .replace("Â«", "<")
        .replace("Â»", ">")
        .replace("Â¨", '"')
        .replace("Â§", "&")
        .replace("«", "<")
        .replace("»", ">")
        .replace("¨", '"')
        .replace("§", "&")
    )

    # Some payloads are already literal XML, but every XML delimiter/quote/entity
    # is prefixed by mojibake NBSP residue: Â<math ... Â" ... Â>.
    # Removing U+00C2 here is MathML-local and prevents corrupting media <img>
    # attributes elsewhere in the pipeline.
    return mathml.replace("\u00c2", "")


def has_children(node, expected):
    return len(node) >= expected


def normalize_latex_for_preview(latex: str) -> str:
    if not latex:
        return ""

    latex = clean_existing_latex(latex)
    latex = repair_known_malformed_latex(latex)

    # Normalize ordinary whitespace only. TeX command boundaries are protected
    # by explicit empty groups such as \times{}h and \div{}x.
    latex = re.sub(r"(\\\ ){2,}", r"\\ ", latex)
    latex = re.sub(r"(?<!\\) {2,}", " ", latex)
    latex = re.sub(r"\s*([<>])\s*", r" \1 ", latex)

    latex = latex.replace(r"\left\{ ", r"\left\{")
    latex = latex.replace(r" \right\}", r"\right\}")
    latex = repair_latex_command_boundaries(latex)
    latex = repair_known_malformed_latex(latex)

    return latex.strip()


def latex_fence_delimiter(value: str, side: str) -> str:
    if value == "":
        return "."
    if value == "{":
        return r"\{"
    if value == "}":
        return r"\}"
    if value == "|":
        return r"\vert"
    return value


# Shared by both the generic math converter (node_to_latex) and the
# chemistry converter (node_to_ce) so <mmultiscripts> (nuclide/isotope
# prescripts, e.g. mass number and atomic number to the left of an element)
# is parsed identically in both -- only how the pieces are rendered differs.
def _mmlscripts_split(node):
    children = list(node)

    if not children:
        return None, [], []

    base = children[0]
    rest = children[1:]

    prescripts_at = next(
        (
            idx for idx, child in enumerate(rest)
            if etree.QName(child).localname == "mprescripts"
        ),
        None
    )

    if prescripts_at is None:
        return base, rest, []

    return base, rest[:prescripts_at], rest[prescripts_at + 1:]


def _mmlscripts_pairs(items):
    it = iter(items)
    return list(zip(it, it))


def _mmlscript_text(script_node, render_fn):
    if script_node is None:
        return ""

    if etree.QName(script_node).localname in {"mnone", "none"}:
        return ""

    return render_fn(script_node) + (script_node.tail or "")


def _mmlscripts_render(pairs, render_fn):
    piece = ""

    for sub_node, sup_node in pairs:
        sup_latex = _mmlscript_text(sup_node, render_fn)
        sub_latex = _mmlscript_text(sub_node, render_fn)

        if sup_latex:
            piece += "^{" + sup_latex + "}"
        if sub_latex:
            piece += "_{" + sub_latex + "}"

    return piece


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

        if value.lower() in MATH_FUNCTIONS:
            return rf"\{value.lower()} "

        if value in GREEK_MAP:
            # Braces terminate the command before any following identifier.
            return f"{{{GREEK_MAP[value]}}}"

        # WIRIS marks upright entities -- chemical element symbols, units --
        # with mathvariant="normal" (see wrs_chemistry equations in Chemistry
        # and Biology content). Without honoring it, a single-letter symbol
        # like H, O or C falls through as bare math text and renders in
        # italic, which is chemically wrong: mhchem's own convention is
        # upright font for chemical entities, italic only for variables.
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
            "±": r"\pm{}",
            "×": r"\times{}",
            "÷": r"\div{}",
            "⋅": r"\cdot{}",
            "·": r"\cdot{}",
            "∞": r"\infty{}",
            "∆": r"\Delta{}",
            "Δ": r"\Delta{}",
            "−": "-",
            "=": " = ",
            "+": "+",
            "-": "-",
            "\u00a0": " ",
            "{": r"\{",
            "}": r"\}",
            "|": r"\mid ",
            "(": "(",
            ")": ")",
            ".": ".",
            ",": ",",
            # Reaction arrows used by wrs_chemistry equations (Chemistry and
            # Biology). Left unmapped, MathJax has no glyph for these
            # characters inside math mode and the arrow silently disappears.
            "→": r"\rightarrow{}",
            "←": r"\leftarrow{}",
            "⇌": r"\rightleftharpoons{}",
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

    # WIRIS chemistry equations use <mmultiscripts> for nuclide/isotope
    # notation (e.g. mass number/atomic number to the LEFT of an element:
    # 24/12-Mg). Per the MathML spec the children are: base, then zero or
    # more (sub, sup) postscript pairs, then an optional <mprescripts/>
    # marker followed by zero or more (sub, sup) prescript pairs. This tag
    # was previously unhandled and fell through to the generic fallback,
    # which concatenated the raw numbers next to the element with no
    # super/subscript -- see mhchem.pdf "Nuclides, Isotopes" for the
    # \ce{^{227}_{90}Th} convention this mirrors using the plain-LaTeX
    # "{}^{}_{}" prescript trick (no mhchem package dependency).
    if tag == "mmultiscripts":

        base, post_children, pre_children = _mmlscripts_split(node)

        if base is None:
            return ""

        if len(post_children) % 2 or len(pre_children) % 2:
            logger.log(
                question_id=None,
                lesson=None,
                question_type="MATHML",
                reason=f"Invalid mmultiscripts: unpaired scripts ({len(post_children)} post, {len(pre_children)} pre)",
                file_path=None
            )

        prescript_latex = _mmlscripts_render(_mmlscripts_pairs(pre_children), node_to_latex)
        postscript_latex = _mmlscripts_render(_mmlscripts_pairs(post_children), node_to_latex)

        # An empty group anchors a leading ^/_ so it attaches as a prescript
        # to the base that follows, rather than to whatever text precedes it.
        result = ("{}" + prescript_latex if prescript_latex else "")
        result += node_to_latex(base) + (base.tail or "")
        result += postscript_latex

        return result

    if tag == "mfenced":

        open_char = node.attrib.get("open", "(")
        close_char = node.attrib.get("close", ")")

        content = "".join(
            node_to_latex(c) + (c.tail or "")
            for c in node
        )

        return (
            r"\left"
            + latex_fence_delimiter(open_char, "open")
            + content
            + r"\right"
            + latex_fence_delimiter(close_char, "close")
        )

    if tag == "mtable":
        rows = [node_to_latex(c) for c in node]
        rows = [row for row in rows if row]
        return r"\begin{array}{l}" + r" \\ ".join(rows) + r"\end{array}"

    if tag == "mtr":
        cells = [node_to_latex(c) for c in node]
        return " & ".join(cell for cell in cells if cell)

    if tag == "mtd":
        return "".join(node_to_latex(c) + (c.tail or "") for c in node)

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

        top_latex = node_to_latex(node[1]).strip()
        base_latex = node_to_latex(node[0])

        if top_latex in {"¯", "-", "ˉ", "\u00af", "&#xAF;", "\u02c9"} or not top_latex:
            return rf"\overline{{{base_latex}}}"

        return (
            r"\overset{"
            + top_latex
            + "}{"
            + base_latex
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

        mathml = sanitize_mathml(decode_wiris_mathml(mathml))

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


# ============================================================================
# Chemistry / Biology MathML -> mhchem (\ce{...}) converter
#
# WIRIS equations authored with the "chemistry" editor (isotopes, molecular
# formulae, reaction arrows, states of matter -- used across Chemistry AND
# Biology content) are tagged <math class="wrs_chemistry"> and need chemistry
# typesetting conventions, not generic math LaTeX. Per mhchem.pdf, mhchem's
# \ce{...} macro parses a compact chemistry syntax itself (element symbols
# stay upright automatically, "^{a}_{b}Elem" is read natively as a nuclide
# prescript with no "{}" anchor needed, "->"/"<-"/"<=>" are reaction arrows,
# "(aq)"/"(s)" etc. are recognized as states of matter). This path is
# completely separate from node_to_latex()/mathml_to_latex() above, which
# remains the Math-subject converter and is untouched by any of this.
# ============================================================================

CE_ARROW_TOKENS = {
    "→": "->",   # →
    "←": "<-",   # ←
    "⇌": "<=>",  # ⇌
}


def is_chemistry_mathml(mathml: str) -> bool:
    return bool(re.search(r'class\s*=\s*"[^"]*wrs_chemistry[^"]*"', mathml or ""))


def _ce_children_text(node):
    return "".join(node_to_ce(c) + (c.tail or "") for c in node)


def _ce_find_arrow_child(row_node):
    for idx, child in enumerate(row_node):
        if etree.QName(child).localname == "mo":
            raw = html.unescape(child.text or "").strip()
            if raw in CE_ARROW_TOKENS:
                return idx, CE_ARROW_TOKENS[raw]
    return None, None


def node_to_ce(node):
    tag = etree.QName(node).localname

    if tag in {"math", "mrow"}:
        return _ce_children_text(node)

    if tag == "mn":
        return (node.text or "").strip()

    if tag == "mi":
        value = (node.text or "").strip()

        if not value:
            return ""

        if value.lower() in MATH_FUNCTIONS:
            return rf"\{value.lower()} "

        if value in GREEK_MAP:
            return f"{{{GREEK_MAP[value]}}}"

        # Unlike node_to_latex(), do NOT wrap element symbols in \text{}:
        # mhchem's own \ce{} parser decides upright vs. italic for chemical
        # entities from the plain text itself, and wrapping it ourselves
        # would hide that text from mhchem's formula/bond/charge detection.
        return escape_latex_text(value)

    if tag == "mo":
        raw = html.unescape(node.text or "")

        if raw in {" ", " "}:
            return " "

        value = raw.strip()

        if not value:
            return " "

        if value in CE_ARROW_TOKENS:
            return CE_ARROW_TOKENS[value]

        mapping = {
            "≤": r"\le{}",
            "≥": r"\ge{}",
            "±": r"\pm{}",
            "×": r"\times{}",
            "÷": r"\div{}",
            "⋅": r"\cdot{}",
            "·": r"\cdot{}",
            "∞": r"\infty{}",
            "∆": r"\Delta{}",
            "Δ": r"\Delta{}",
            "−": "-",
            # mhchem tokenizes \ce{...}'s own argument; unescaped braces
            # would prematurely close that argument (mhchem.pdf: "Write
            # braces as \{ \}."). "+", "-", "=", "(", ")" are intentionally
            # NOT mapped here -- mhchem reads those raw to detect charges,
            # bonds and equation operators.
            "{": r"\{",
            "}": r"\}",
        }

        return mapping.get(value, value)

    if tag == "mtext":
        text = (node.text or " ").strip()
        return escape_latex_text(text) if text else " "

    if tag == "mspace":
        if node.attrib.get("linebreak") == "newline":
            return "\\\\ "
        return " "

    if tag == "mfrac":

        if not has_children(node, 2):
            logger.log(
                question_id=None,
                lesson=None,
                question_type="MATHML_CE",
                reason=f"Invalid mfrac(ce): expected 2 children got {len(node)}",
                file_path=None
            )
            return _ce_children_text(node)

        return (
            r"\frac{"
            + node_to_ce(node[0]) + (node[0].tail or "")
            + "}{"
            + node_to_ce(node[1]) + (node[1].tail or "")
            + "}"
        )

    if tag == "msup":

        if not has_children(node, 2):
            logger.log(
                question_id=None,
                lesson=None,
                question_type="MATHML_CE",
                reason=f"Invalid msup(ce): expected 2 children got {len(node)}",
                file_path=None
            )
            return _ce_children_text(node)

        return (
            node_to_ce(node[0]) + (node[0].tail or "")
            + "^{"
            + node_to_ce(node[1]) + (node[1].tail or "")
            + "}"
        )

    if tag == "msub":

        if not has_children(node, 2):
            logger.log(
                question_id=None,
                lesson=None,
                question_type="MATHML_CE",
                reason=f"Invalid msub(ce): expected 2 children got {len(node)}",
                file_path=None
            )
            return _ce_children_text(node)

        return (
            node_to_ce(node[0]) + (node[0].tail or "")
            + "_{"
            + node_to_ce(node[1]) + (node[1].tail or "")
            + "}"
        )

    if tag == "msubsup":

        if len(node) < 3:
            logger.log(
                question_id=None,
                lesson=None,
                question_type="MATHML_CE",
                reason=f"Invalid msubsup(ce): expected 3 children got {len(node)}",
                file_path=None
            )
            return _ce_children_text(node)

        return (
            node_to_ce(node[0]) + (node[0].tail or "")
            + "_{"
            + node_to_ce(node[1]) + (node[1].tail or "")
            + "}^{"
            + node_to_ce(node[2]) + (node[2].tail or "")
            + "}"
        )

    if tag == "mmultiscripts":

        base, post_children, pre_children = _mmlscripts_split(node)

        if base is None:
            return ""

        if len(post_children) % 2 or len(pre_children) % 2:
            logger.log(
                question_id=None,
                lesson=None,
                question_type="MATHML_CE",
                reason=f"Invalid mmultiscripts(ce): unpaired scripts ({len(post_children)} post, {len(pre_children)} pre)",
                file_path=None
            )

        prescript_latex = _mmlscripts_render(_mmlscripts_pairs(pre_children), node_to_ce)
        postscript_latex = _mmlscripts_render(_mmlscripts_pairs(post_children), node_to_ce)

        # mhchem's \ce{} parser recognizes a leading ^/_ as a nuclide
        # prescript on its own (mhchem.pdf: \ce{^{227}_{90}Th}) -- no "{}"
        # anchor needed here, unlike the generic math path.
        result = prescript_latex
        result += node_to_ce(base) + (base.tail or "")
        result += postscript_latex

        return result

    if tag == "mover":

        if len(node) < 2:
            logger.log(
                question_id=None,
                lesson=None,
                question_type="MATHML_CE",
                reason=f"Invalid mover(ce): expected 2 children got {len(node)}",
                file_path=None
            )
            return _ce_children_text(node)

        base, over = node[0], node[1]
        over_latex = node_to_ce(over) + (over.tail or "")
        base_tag = etree.QName(base).localname

        # A bare arrow with a label above it (e.g. an electron-transfer
        # annotation) maps directly to mhchem's own "->[label]" syntax,
        # which renders the label above the arrow (mhchem.pdf "Reaction
        # Arrows": \ce{A ->[H2O] B}).
        # WIRIS still emits the arrow-with-condition template even when the
        # author left the condition blank (an empty <mrow/> overscript) --
        # e.g. an electrolysis arrow typed with no label. Emit a plain arrow
        # rather than a bracket with nothing in it.
        label = f"[{over_latex}]" if over_latex.strip() else ""

        if base_tag == "mo":
            raw = html.unescape(base.text or "").strip()
            if raw in CE_ARROW_TOKENS:
                return CE_ARROW_TOKENS[raw] + label

        # The arrow is sometimes buried inside a larger <mrow> alongside the
        # rest of the equation (e.g. "2H2O(l) [arrow] 2H2(g) + O2(g)" with a
        # condition such as "electrolysis" written above the arrow). Splice
        # the "[label]" in at the arrow's position instead of dropping it.
        if base_tag in {"mrow", "math"}:
            arrow_idx, token = _ce_find_arrow_child(base)
            if token is not None:
                base_children = list(base)
                before = "".join(
                    node_to_ce(c) + (c.tail or "")
                    for c in base_children[:arrow_idx]
                )
                after = "".join(
                    node_to_ce(c) + (c.tail or "")
                    for c in base_children[arrow_idx + 1:]
                )
                return before + token + label + after

        logger.log(
            question_id=None,
            lesson=None,
            question_type="MATHML_CE",
            reason="mover(ce) with no recognizable arrow base; overscript label dropped",
            file_path=None
        )
        return node_to_ce(base) + (base.tail or "")

    if tag == "mfenced":

        open_char = node.attrib.get("open", "(")
        close_char = node.attrib.get("close", ")")

        content = _ce_children_text(node)

        # mhchem.pdf: "Use parenthesis ( ) and brackets [ ] normally" --
        # only fall back to \left/\right (a math-mode-only feature) for
        # anything mhchem wouldn't already understand on its own, such as
        # braces.
        if open_char in {"(", "[", ""} and close_char in {")", "]", ""}:
            return f"{open_char}{content}{close_char}"

        return (
            r"\left"
            + latex_fence_delimiter(open_char, "open")
            + content
            + r"\right"
            + latex_fence_delimiter(close_char, "close")
        )

    # Any tag not explicitly handled above (e.g. munder, menclose, mtable)
    # falls back to rendering its children so the surrounding formula
    # survives instead of the whole equation disappearing.
    return _ce_children_text(node)


def mathml_to_ce(mathml, question_id, lesson):

    try:

        mathml = sanitize_mathml(decode_wiris_mathml(mathml))

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

        body = node_to_ce(root).strip()

        if not body:
            return ""

        return r"\ce{" + body + "}"

    except Exception as ex:

        print("\n======================")
        print("FAILED CHEMISTRY MATHML")
        print(mathml)
        print("======================")
        print(ex)
        if logger:
            logger.log(
                question_id=question_id,
                lesson=lesson,
                question_type="MATHML_CE",
                reason=str(ex),
                file_path=None
            )
        return ""


def mathml_to_latex_auto(mathml, question_id, lesson):
    """Route WIRIS MathML to the chemistry (mhchem) converter for
    Chemistry/Biology "wrs_chemistry" equations, and to the generic math
    converter for everything else (Math subject content is untouched)."""

    if is_chemistry_mathml(mathml):
        return mathml_to_ce(mathml, question_id, lesson)

    return mathml_to_latex(mathml, question_id, lesson)


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


def  parse_html_content(html_content, question_id, lesson, extract_table=True):
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
                latex = mathml_to_latex_auto(mathml, question_id, lesson)
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
                latex = mathml_to_latex_auto(mathml, question_id, lesson)

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

    normalize_plain_latex_text_nodes(soup)

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
    # Tables
    # ========================================================

    # Destinations typed as Html[] (outcomeDeclaration.feedback.*,
    # itemBody.options[].feedback) have no "table" field and require every
    # item to carry "text" - a table there must stay inline HTML instead of
    # becoming a separate table content item.
    table_items = extract_tables(soup, question_id, lesson) if extract_table else []

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

    contents.extend(table_items)

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


def split_html_only_feedback_content(items, question_id=None, lesson=None):
    """Adapt parse_html_content() output for Html[]-only feedback destinations
    (FeedbackContent.content, used by outcomeDeclaration.feedback.* and
    itemBody.options[].feedback): every content item there requires "text"
    and there is no "table"/"video" field, only a single sibling "audio"
    field - unlike ContentItem[] destinations (statement/seeWhy/needHelp).
    """
    content = []
    audio = None

    for item in items or []:
        item_type = item.get("type")

        if item_type == "image":
            item = dict(item)
            item["text"] = ""
            content.append(item)

        elif item_type == "audio":
            if audio is None:
                audio = item.get("audio")
            if logger:
                logger.log(
                    question_id=question_id,
                    lesson=lesson,
                    question_type="FEEDBACK_AUDIO",
                    reason="Moved inline <audio> into FeedbackContent.audio",
                    file_path=None
                )

        elif item_type == "video":
            if logger:
                logger.log(
                    question_id=question_id,
                    lesson=lesson,
                    question_type="FEEDBACK_VIDEO_DROPPED",
                    reason="Dropped <video> - FeedbackContent has no video field",
                    file_path=None
                )

        else:
            content.append(item)

    return content, audio
