from parsers.content_parser import parse_html_content
from bs4 import BeautifulSoup


def _extract_audio_from_prompt(html):
    """Detect first <audio> tag in HTML, return cleaned HTML + audio dict."""
    if not html:
        return html, None

    soup = BeautifulSoup(html, "html.parser")
    audio_tag = soup.find("audio")
    if audio_tag:
        src = audio_tag.get("src")
        if not src:
            source_tag = audio_tag.find("source")
            if source_tag:
                src = source_tag.get("src")
        audio_tag.decompose()
        cleaned = str(soup).strip()
        if src:
            return cleaned, {"url": src}
        return cleaned, None

    return html, None


def _extract_video_from_prompt(html):
    """Detect first <video> tag in HTML, return cleaned HTML + video dict."""
    if not html:
        return html, None

    soup = BeautifulSoup(html, "html.parser")
    video_tag = soup.find("video")
    if video_tag:
        src = video_tag.get("src")
        if not src:
            source_tag = video_tag.find("source")
            if source_tag:
                src = source_tag.get("src")
        video_tag.decompose()
        cleaned = str(soup).strip()
        if src:
            return cleaned, {"url": src}
        return cleaned, None

    return html, None


def build_image_labelling_dnd_item_body(raw,question_id,lesson):

    body = raw.get("body", {})

    choices = body.get("choices", {})

    background_image = body.get("backgroundImage")
    if background_image and "src" in background_image:
        background_image["url"] = background_image.pop("src")

    prompt = body.get("prompt")
    prompt, audio = _extract_audio_from_prompt(prompt)
    prompt, video = _extract_video_from_prompt(prompt)

    return {

        "version": "1.0",

        "title": None,

        "subTitle": None,

        "instruction": None,

        "audio": audio,

        "video": video,

        "statement": None,

        "sentence": None,

        "image": background_image,

        "showDragHandle":
            choices.get(
                "showDragHandle",
                True
            ),

        "shuffled":
            choices.get(
                "shuffle",
                True
            ),

        "optionsStyle": "option-style-1",

        "dropLimit": 1,

        "optionsPosition": "bottom",

        "sideImage": None,

        "backgroundLayout": None,

        "splitContent": None,

        "timeSpentConfig": None,

        "targets":
            build_targets(
                body.get(
                    "blanks",
                    []
                )
            ),

        "options":
            build_image_labelling_options(
                choices.get(
                    "choiceItems",
                    []
                ),question_id,lesson
            )
    }


def build_targets(blanks):

    targets = []

    for index, blank in enumerate(blanks, start=1):

        targets.append({

            "id": index,

            "weight": round(
                (
                    blank.get(
                        "weight",
                        0
                    ) / 100
                ),
                4
            ),

            "swappable": False,

            "swapGroupId": 0,

            "position": {

                "Top":
                    blank.get(
                        "position",
                        {}
                    ).get("y"),

                "Left":
                    blank.get(
                        "position",
                        {}
                    ).get("x")
            }
        })

    if targets:
        total_weight = sum(t["weight"] for t in targets)
        if total_weight > 0 and round(total_weight, 4) != 1.0:
            diff = 1.0 - total_weight
            targets[0]["weight"] = round(targets[0]["weight"] + diff, 4)

    return targets


def build_image_labelling_options(choice_items,question_id,lesson):

    options = []

    for index, choice in enumerate(choice_items, start=1):

        raw_value = choice.get("value", "")
        content_obj = None

        if raw_value:
            soup = BeautifulSoup(raw_value, "html.parser")
            audio_tag = soup.find("audio")
            if audio_tag:
                src = audio_tag.get("src")
                if not src:
                    source_tag = audio_tag.find("source")
                    if source_tag:
                        src = source_tag.get("src")
                audio_tag.decompose()
                if src:
                    content_obj = {"type": "audio", "audio": {"url": src}}

            if not content_obj:
                video_tag = soup.find("video")
                if video_tag:
                    src = video_tag.get("src")
                    if not src:
                        source_tag = video_tag.find("source")
                        if source_tag:
                            src = source_tag.get("src")
                    video_tag.decompose()
                    if src:
                        content_obj = {"type": "video", "video": {"url": src}}

            if content_obj:
                raw_value = str(soup).strip()

        if not content_obj:
            parsed_content = parse_html_content(
                raw_value,
                question_id,
                lesson
            )

            sorted_content = _sort_option_content(
                parsed_content
            )

            content_obj = sorted_content[0] if sorted_content else {"type": "text", "text": ""}

        option = {

            "id": index,

            "content": content_obj
        }

        options.append(option)

    return options


def _sort_option_content(contents):

    image_items = []

    other_items = []

    for item in contents:

        if item.get("type") == "image":

            image_items.append(item)

        else:

            other_items.append(item)

    return image_items + other_items
 