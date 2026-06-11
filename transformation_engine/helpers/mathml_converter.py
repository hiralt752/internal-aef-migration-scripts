from bs4 import BeautifulSoup
import html
import urllib.parse


def process_html_and_convert_math(value_html: str) -> str:
    if not value_html:
        return ""

    soup = BeautifulSoup(value_html or "", "html.parser")

    for img in soup.find_all("img"):
        src = img.get("src", "")
        if src and src.startswith("data:image/svg+xml") and "mathml" in urllib.parse.unquote(src).lower():
            latex = (img.get("data-latex") or img.get("alt") or "").strip()
            replacement = f"\\({latex}\\)" if latex else ""
            img.replace_with(replacement)

    text = soup.get_text(separator="", strip=False)
    return html.unescape(text).strip()
