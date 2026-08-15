from bs4 import BeautifulSoup, NavigableString
import html
import urllib.parse
from parsers.content_parser import (
    mathml_to_latex,
    normalize_latex_for_preview,
    normalize_math_words,
    clean_existing_latex,
    extract_mathml_from_svg,
    normalize_plain_latex_text_nodes,
)


def process_html_and_convert_math(value_html: str) -> str:
    if not value_html:
        return ""

    soup = BeautifulSoup(value_html or "", "html.parser")

    # ------------------------------------------------------------------
    # Convert Wiris equation <img> tags into inline LaTeX: \( ... \)
    # ------------------------------------------------------------------
    for img in soup.find_all("img"):
        src = img.get("src", "") or ""
        classes = img.get("class") or []
        is_wiris = (
            "Wirisformula" in classes
            or (
                src.startswith("data:image/svg+xml")
                and "mathml" in urllib.parse.unquote(src).lower()
            )
            or bool(img.get("data-mathml"))
        )

        if not is_wiris:
            continue

        latex = ""

        if img.get("data-mathml"):
            latex = mathml_to_latex(img.get("data-mathml"), None, None)

        if not latex and src.startswith("data:image/svg+xml"):
            extracted = extract_mathml_from_svg(src)
            if extracted:
                latex = mathml_to_latex(extracted, None, None)

        if not latex and img.get("data-latex"):
            latex = clean_existing_latex(img.get("data-latex", ""))

        if not latex:
            latex = clean_existing_latex(img.get("alt", ""))

        if latex:
            latex = normalize_latex_for_preview(latex)
            latex = normalize_math_words(latex)

        replacement = f" \\({latex}\\) " if latex else ""
        img.replace_with(NavigableString(replacement))

    # ------------------------------------------------------------------
    # Some source HTML types raw LaTeX directly as text instead of using a
    # Wiris equation image, e.g. "\cos {\theta} = ____". Without this step
    # that text passes through untouched: it never gets wrapped in \( \),
    # so MathJax never picks it up and it renders as literal backslashes
    # and braces on the page (exactly the bug in the screenshots).
    # ------------------------------------------------------------------
    normalize_plain_latex_text_nodes(soup)

    text = soup.get_text(separator="", strip=False)
    return html.unescape(text).strip()