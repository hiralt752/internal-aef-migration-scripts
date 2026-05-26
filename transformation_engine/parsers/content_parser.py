from bs4 import BeautifulSoup


def parse_html_content(html):

    soup = BeautifulSoup(
        html or "",
        "html.parser"
    )

    contents = []

    text = soup.get_text(
        separator=" ",
        strip=True
    )

    if text:

        contents.append({
            "type": "text",
            "text": text
        })

    for img in soup.find_all("img"):

        src = img.get("src")

        if src:

            contents.append({
                "type": "image",
                "image": {
                    "url": src,
                    "zoom": True
                }
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