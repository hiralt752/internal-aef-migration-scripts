from bs4 import BeautifulSoup

def _get_soup(html):
    return BeautifulSoup(html or "", "html.parser")


def _clean_src(src):
    if not src:
        return None

    src = src.strip()

    return src if src else None


def extract_audio(html):
    soup = _get_soup(html)

    audio = soup.find("audio")
    if not audio:
        return None

    src = audio.get("src")

    if not src:
        source = audio.find("source")
        if source:
            src = source.get("src")

    src = _clean_src(src)

    if not src:
        return None

    return {
        "url": src
    }

def extract_video(html):
    soup = _get_soup(html)

    video = soup.find("video")
    if not video:
        return None

    src = video.get("src")

    if not src:
        source = video.find("source")
        if source:
            src = source.get("src")

    src = _clean_src(src)

    if not src:
        return None

    return {
        "url": src
    }



def extract_image(html):
    soup = _get_soup(html)

    image = soup.find("img")
    if not image:
        return None

    src = image.get("src")

    src = _clean_src(src)

    if not src:
        return None

    return {
        "url": src
    }