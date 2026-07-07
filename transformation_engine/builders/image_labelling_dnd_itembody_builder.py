from parsers.content_parser import parse_html_content
from bs4 import BeautifulSoup


def _get_media_src(tag):
    if not tag:
        return None

    src = tag.get("src")
    if src:
        src = src.strip()
        if src:
            return src

    source = tag.find("source")
    if source:
        src = source.get("src")
        if src:
            src = src.strip()
            if src:
                return src

    return None


def _extract_prompt_media(html):
    if not html:
        return None, None

    soup = BeautifulSoup(html, "html.parser")

    audio_tag = soup.find("audio")
    video_tag = soup.find("video")

    audio = None
    video = None

    if audio_tag:
        audio_src = _get_media_src(audio_tag)
        if audio_src:
            audio = {"url": audio_src}

    if video_tag:
        video_src = _get_media_src(video_tag)
        if video_src:
            video = {"url": video_src}

    return audio, video


def build_image_labelling_dnd_item_body(raw,question_id,lesson):

    body = raw.get("body", {})

    choices = body.get("choices", {})
    audio, video = _extract_prompt_media(body.get("prompt"))

    background_image = body.get("backgroundImage")
    if background_image and "src" in background_image:
        background_image["url"] = background_image.pop("src")

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

        parsed_content = parse_html_content(
            choice.get(
                "value",
                ""
            ),question_id,lesson
        )

        sorted_content = _sort_option_content(
            parsed_content
        )

        option = {

            "id": index,

            "content":
                sorted_content[0]
                if sorted_content
                else {"type": "text", "text": ""}
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
 