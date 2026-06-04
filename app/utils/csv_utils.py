from collections import Counter

import pandas as pd


def read_question_ids(csv_path):
    """
    Read Question IDs from CSV.

    Expected Format:
    - UTF-16
    - Tab Separated
    - Question Id column

    Returns:
        list[str]

    Raises:
        ValueError
    """

    try:

        df = pd.read_csv(
            csv_path,
            encoding="utf-16",
            sep="\t"
        )

    except UnicodeDecodeError:

        raise ValueError(
            f"""
Invalid CSV Encoding

File:
{csv_path}

Expected:
UTF-16

Possible Causes:
- File saved as UTF-8
- File saved as ANSI
- File exported incorrectly

Please re-save the file as:
UTF-16 Tab Delimited
"""
        )

    except Exception as exception:

        raise ValueError(
            f"""
Failed to read CSV file

File:
{csv_path}

Error:
{str(exception)}
"""
        )

    df.columns = df.columns.str.strip()

    if "Question Id" not in df.columns:

        raise ValueError(
            f"""
Missing Required Column

File:
{csv_path}

Required Column:
Question Id
"""
        )

    return (
        df["Question Id"]
        .dropna()
        .astype(str)
        .tolist()
    )


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