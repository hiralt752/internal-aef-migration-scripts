from collections import Counter

import pandas as pd


def read_question_ids(
    csv_path
):
    """
    Read Question IDs from CSV.
    """

    df = pd.read_csv(
        csv_path,
        encoding="utf-16",
        sep="\t"
    )

    df.columns = (
        df.columns
        .str.strip()
    )

    if (
        "Question Id"
        not in df.columns
    ):
        raise ValueError(
            f"'Question Id' column "
            f"missing in {csv_path}"
        )

    question_ids = (
        df["Question Id"]
        .dropna()
        .astype(str)
        .tolist()
    )

    return question_ids


def build_question_stats(
    question_ids
):
    """
    Returns:

    unique_question_ids
    duplicate_counter
    total_count
    unique_count
    duplicate_count
    """

    counter = Counter(
        question_ids
    )

    unique_question_ids = list(
        counter.keys()
    )

    total_count = len(
        question_ids
    )

    unique_count = len(
        unique_question_ids
    )

    duplicate_count = (
        total_count
        - unique_count
    )

    return (
        unique_question_ids,
        counter,
        total_count,
        unique_count,
        duplicate_count
    )