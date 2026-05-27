from bs4 import BeautifulSoup
import urllib.parse


def parse_html_content(html):

    soup = BeautifulSoup(
        html or "",
        "html.parser"
    )

    contents = []

    for img in soup.find_all("img"):

        src = img.get("src", "")

        if not src:
            continue

        if (
            src.startswith("data:image/svg+xml")
            and "mathml" in urllib.parse.unquote(src).lower()
        ):

            latex = (
                img.get("data-latex")
                or img.get("alt")
                or ""
            ).strip()

            img.replace_with(f"\\({latex}\\)")

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

    remaining_html = str(soup).strip()

    if remaining_html:

        contents.insert(0, {
            "type": "text",
            "text": remaining_html
        })

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