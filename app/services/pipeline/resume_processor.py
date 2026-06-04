import os

import pandas as pd
import pandas as pd
from pandas.errors import EmptyDataError
from json import load


class ResumeProcessor:

    @staticmethod
    def get_remaining_question_ids(
        subject_output_dir,
        unique_question_ids
    ):
        """
        Determine which question IDs still need processing.

        Reads:

        success_question_log.csv
        failure_question_log.csv

        Returns:

        remaining_ids
        already_processed_count
        """

        processed_ids = set()

        success_file = os.path.join(
            subject_output_dir,
            "success_question_log.csv"
        )

        failure_file = os.path.join(
            subject_output_dir,
            "failure_question_log.csv"
        )

        if os.path.exists(success_file):

            try:

                success_df = safe_read_csv(
                    success_file
                )

            except EmptyDataError:

                success_df = pd.DataFrame()

            processed_ids.update(
                success_df[
                    "question_id"
                ].astype(str)
            )

        if os.path.exists(failure_file):

            try:

                failure_df = safe_read_csv(
                    failure_file
                )

            except EmptyDataError:

                failure_df = pd.DataFrame()

            if (
                not success_df.empty
                and "question_id" in success_df.columns
            ):

                processed_ids.update(
                    success_df[
                        "question_id"
                    ].astype(str)
                )

        remaining_ids = [

            str(question_id)

            for question_id
            in unique_question_ids

            if str(question_id)
            not in processed_ids
        ]

        return (
            remaining_ids,
            len(processed_ids)
        )

def should_resume(
    metadata_file
):
        if not os.path.exists(
        metadata_file
        ):
            return False

        metadata = load(
            metadata_file
        )

        return (
            metadata.get("status")
            == "INTERRUPTED"
        )

import pandas as pd
from pandas.errors import EmptyDataError


def safe_read_csv(
    file_path
):
    """
    Safely read CSV.

    Returns empty DataFrame if:
    - file is empty
    - file is corrupted
    - file missing headers
    """

    try:

        df = pd.read_csv(
            file_path
        )

        return df

    except (
        EmptyDataError,
        pd.errors.ParserError,
        FileNotFoundError
    ):

        return pd.DataFrame()