import os

import pandas as pd


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

            success_df = pd.read_csv(
                success_file
            )

            processed_ids.update(
                success_df[
                    "question_id"
                ].astype(str)
            )

        if os.path.exists(failure_file):

            failure_df = pd.read_csv(
                failure_file
            )

            processed_ids.update(
                failure_df[
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