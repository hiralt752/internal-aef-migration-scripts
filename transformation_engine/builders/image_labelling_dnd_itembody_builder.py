from parsers.content_parser import parse_html_content
from bs4 import BeautifulSoup
from helpers.dnd_position_scaler import calculate_imd_dnd_target_position


MAIN_IMAGE_LAYOUTS = {
    "Drag and Drop (mainimage)": {
        "width": 560,
        "height": 315,
    },
    "Drag and Drop (4imageoptions)": {
        "width": 560,
        "height": 315,
    },
    "Drag and Drop (SplitScreenImage)": {
        "width": 252,
        "height": 189,
    },
    "fallback":{
        "width": 600,
        "height": 338,
    }
}

FALLBACK_IMAGE_LAYOUT = {
    "width": 600,
    "height": 338,
}


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


def _has_image_option(choice):

    value = choice.get("value", "")
    if not value:
        return False

    soup = BeautifulSoup(value, "html.parser")
    return soup.find("img") is not None


def _resolve_main_image_dimensions(background_image, choice_items):

    option_image_count = sum(
        1 for choice in choice_items
        if _has_image_option(choice)
    )

    widget_type = None

    if background_image:
        if option_image_count > 0 :
            if option_image_count == 4:
                widget_type = "Drag and Drop (4imageoptions)"
            elif option_image_count <= 2 :
                widget_type = "Drag and Drop (SplitScreenImage)"
            elif option_image_count > 0:
                widget_type = "Drag and Drop (mainimage)"
            else:
                widget_type = "fallback"
        else:
            widget_type = "Drag and Drop (mainimage)"

    if widget_type in MAIN_IMAGE_LAYOUTS:
        print("MAIN_IMAGE_LAYOUTS",MAIN_IMAGE_LAYOUTS[widget_type])
        return MAIN_IMAGE_LAYOUTS[widget_type]

    return FALLBACK_IMAGE_LAYOUT


def _scale_coordinate(value, dimension):

    if value is None or dimension is None:
        return None

    try:
        numeric_value = float(value)
    except (TypeError, ValueError):
        return None

    return round(numeric_value * dimension)


def _build_background_image(background_image, rendered_dimensions):

    if not background_image:
        return background_image

    transformed_image = dict(background_image)

    if "src" in transformed_image:
        transformed_image["url"] = transformed_image.pop("src")

    if rendered_dimensions.get("width") is not None:
        transformed_image["width"] = rendered_dimensions["width"]

    if rendered_dimensions.get("height") is not None:
        transformed_image["height"] = rendered_dimensions["height"]

    return transformed_image


def build_image_labelling_dnd_item_body(raw,question_id,lesson):

    body = raw.get("body", {})

    choices = body.get("choices", {})
    audio, video = _extract_prompt_media(body.get("prompt"))

    background_image = body.get("backgroundImage")
    rendered_dimensions = _resolve_main_image_dimensions(
        background_image,
        choices.get("choiceItems", [])
    )
    background_image = _build_background_image(
        background_image,
        rendered_dimensions
    )

    return {

        "version": "1.0",

        "title": None,

        "subTitle": None,

        "instruction": None,

        "audio": audio,

        "video": video,

        "statement": {
            "content": {
                "type": "text",
                "text": "<p></p>"
            }
            },

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
                ),
                rendered_dimensions,
                raw_bg_image=body.get("backgroundImage")
            ),

        "options":
            build_image_labelling_options(
                choices.get(
                    "choiceItems",
                    []
                ),question_id,lesson
            )
    }


def build_targets(blanks, rendered_dimensions, raw_bg_image=None):

    raw_bg_w = raw_bg_image.get("width") if raw_bg_image else None
    raw_bg_h = raw_bg_image.get("height") if raw_bg_image else None
    target_vw = rendered_dimensions.get("width", 560)
    target_vh = rendered_dimensions.get("height", 315)

    targets = []

    for index, blank in enumerate(blanks, start=1):
        pos = blank.get("position", {}) or {}
        x_dec = pos.get("x")
        y_dec = pos.get("y")

        scaled_pos = calculate_imd_dnd_target_position(
            x_decimal=x_dec,
            y_decimal=y_dec,
            raw_bg_width=raw_bg_w,
            raw_bg_height=raw_bg_h,
            target_viewport_width=target_vw,
            target_viewport_height=target_vh,
            target_box_width=120
        )

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

            "position": scaled_pos
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
 
