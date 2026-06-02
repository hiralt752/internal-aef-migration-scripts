import json
import os

from config.settings import (
    REPORT_DIR
)


class ReportRepository:

    @staticmethod
    def save_report(
        job_id,
        report
    ):

        os.makedirs(
            REPORT_DIR,
            exist_ok=True
        )

        filepath = os.path.join(
            REPORT_DIR,
            f"{job_id}_report.json"
        )

        with open(
            filepath,
            "w",
            encoding="utf-8"
        ) as f:

            json.dump(
                report,
                f,
                ensure_ascii=False,
                indent=2
            )