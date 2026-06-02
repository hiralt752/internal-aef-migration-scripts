import json
import os


def save_metadata(
    filepath,
    metadata
):

    with open(
        filepath,
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            metadata,
            file,
            ensure_ascii=False,
            indent=2
        )


def load_metadata(
    filepath
):

    if not os.path.exists(
        filepath
    ):
        return None

    with open(
        filepath,
        "r",
        encoding="utf-8"
    ) as file:

        return json.load(file)