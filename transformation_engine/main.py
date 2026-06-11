import json
from pathlib import Path

from transformers.mcq_transformer import MCQTransformer
from transformers.msq_transformer import MSQTransformer
from transformers.dropdown_transformer import DropdownTransformer
from transformers.matching_transformer import MatchingTransformer
from transformers.fib_transformer import FIBTransformer
from transformers.dnd_transformer import DNDTransformer


INPUT_DIR = Path("data_source/transformation/input")
OUTPUT_DIR = Path("data_source/transformation/output")
SUPPORTED_EXTENSIONS = {".json"}


TRANSFORMER_BY_TYPE = {
    "MULTIPLE_CHOICE": MCQTransformer,
    "MULTIPLE_SELECTION": MSQTransformer,
    "SELECT_A_BLANK": DropdownTransformer,
    "MATCHING": MatchingTransformer,
    "FILL_IN_THE_BLANK": FIBTransformer,
    "FILL_IN_THE_BLANK_DRAG_DROP": DNDTransformer,
    "IMAGE_LABELLING_DRAG_DROP": DNDTransformer,
}


def get_transformer(question_type, raw):
    if raw.get("response"):
        raw = raw.get("response")
        question_type = raw.get("type")

    transformer_cls = TRANSFORMER_BY_TYPE.get(question_type)
    if transformer_cls is None:
        raise Exception(f"Unsupported type: {question_type}")
    return transformer_cls(raw)


def load_json_file(path: Path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_json_file(path: Path, data):
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def transform_question(raw_question):
    transformer = get_transformer(raw_question.get("type"), raw_question)
    return transformer.transform()


def transform_file(input_path: Path, output_path: Path):
    raw_data = load_json_file(input_path)
    transformed = []

    if isinstance(raw_data, list):
        for question in raw_data:
            transformed.append(transform_question(question))
    elif isinstance(raw_data, dict):
        transformed.append(transform_question(raw_data))
    else:
        raise Exception(f"Unsupported JSON structure in {input_path}")

    write_json_file(output_path, transformed)


def main():
    INPUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    input_files = [
        path for path in sorted(INPUT_DIR.iterdir())
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS
    ]

    if not input_files:
        raise Exception(f"No JSON files found in {INPUT_DIR}")

    for input_path in input_files:
        output_path = OUTPUT_DIR / input_path.name
        transform_file(input_path, output_path)


if __name__ == "__main__":
    main()
