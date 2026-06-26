import json
from pathlib import Path


def read_json_file(file_path, default=None):
    file_path = Path(file_path)

    if not file_path.exists():
        return default

    try:
        with open(
            file_path,
            "r",
            encoding="utf-8"
        ) as f:
            return json.load(f)

    except Exception:
        return default


def write_json_file(file_path, data):
    file_path = Path(file_path)

    file_path.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    with open(
        file_path,
        "w",
        encoding="utf-8"
    ) as f:
        json.dump(
            data,
            f,
            indent=2,
            ensure_ascii=False
        )


def append_jsonl(file_path, data):
    file_path = Path(file_path)

    file_path.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    with open(
        file_path,
        "a",
        encoding="utf-8"
    ) as f:
        f.write(
            json.dumps(
                data,
                ensure_ascii=False
            )
            + "\n"
        )
