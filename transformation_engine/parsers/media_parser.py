from bs4 import BeautifulSoup


def extract_audio(html):

    soup = BeautifulSoup(
        html or "",
        "html.parser"
    )

    audio = soup.find("audio")

    if not audio:
        return None

    src = audio.get("src")

    if not src:

        source = audio.find("source")

        if source:
            src = source.get("src")

    if not src:
        return None

    return {
        "url": src
    }


def extract_video(html):

    soup = BeautifulSoup(
        html or "",
        "html.parser"
    )

    video = soup.find("video")

    if not video:
        return None

    src = video.get("src")

    if not src:

        source = video.find("source")

        if source:
            src = source.get("src")

    if not src:
        return None

    return {
        "url": src
    }


def extract_image(html):

    soup = BeautifulSoup(
        html or "",
        "html.parser"
    )

    image = soup.find("img")

    if not image:
        return None

    src = image.get("src")

    if not src:
        return None

    return {
        "url": src
    }