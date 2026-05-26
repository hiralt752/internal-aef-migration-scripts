import json

from transformers.mcq_transformer import MCQTransformer
from transformers.msq_transformer import MSQTransformer


INPUT_FILE = "data_source/transformation/transformation_question.json"
OUTPUT_FILE = "data_source/transformation/transformation_output.json"


def get_transformer(question_type, raw):

    if question_type == "MULTIPLE_CHOICE":
        return MCQTransformer(raw)

    if question_type == "MULTIPLE_SELECTION":
        return MSQTransformer(raw)

    raise Exception(f"Unsupported type: {question_type}")


def main():

    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        raw_data = json.load(f)

    transformed = []

    if isinstance(raw_data, list):

        for question in raw_data:

            transformer = get_transformer(
                question.get("type"),
                question
            )

            transformed.append(
                transformer.transform()
            )

    elif isinstance(raw_data, dict):

        transformer = get_transformer(
            raw_data.get("type"),
            raw_data
        )

        transformed.append(
            transformer.transform()
        )

    with open(
        OUTPUT_FILE,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            transformed,
            f,
            indent=2,
            ensure_ascii=False
        )


if __name__ == "__main__":
    main()