from bs4 import BeautifulSoup


def _extract_style(tag):
    return (tag.get("style") or "").lower()


def _detect_layout(html_text: str):

    soup = BeautifulSoup(html_text or "", "html.parser")

    images = soup.find_all("img")
    text = soup.get_text(strip=True)

    if not text or not images:
        return None, 0

    img_count = len(images)

    for img in images:

        style = _extract_style(img)
        parent_style = _extract_style(img.parent) if img.parent else ""

        combined = style + " " + parent_style

        if "float:right" in combined or "text-align:right" in combined:
            return None, img_count

        if (
            "flex-direction: column" in combined
            or "display:block" in combined
            or ("position:absolute" in combined and "bottom" in combined)
        ):
            return "bottom", img_count

    elements = []

    for tag in soup.find_all(["p", "div", "span", "img"]):

        if tag.name == "img":
            elements.append("image")

        elif tag.get_text(strip=True):
            elements.append("text")

    if "text" in elements and "image" in elements:

        first_text = elements.index("text")
        last_image = len(elements) - 1 - elements[::-1].index("image")

        if last_image > first_text:
            return "bottom", img_count

    return None, img_count


def get_see_why_widget_type(html_text: str):

    position, img_count = _detect_layout(html_text)

    if not position:
        return None

    if img_count == 1:
        return "See Why/Need Help (mainimage)"

    if img_count >= 2:
        return "See Why/Need Help (twoimages)"

    return None