import json
from pathlib import Path


def read_json_file(file_path):
    with open(
        file_path,
        "r",
        encoding="utf-8"
    ) as f:
        data = json.load(f)

    if isinstance(data, list):
        return data

    return [data]


def iter_question_files(transformed_data_dir):
    transformed_data_dir = Path(
        transformed_data_dir
    )

    return sorted(
        transformed_data_dir.rglob("*.json")
    )
