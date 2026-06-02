import json
import os

from datetime import datetime

from config.settings import (
    ACTIVE_JOB_DIR,
    COMPLETED_JOB_DIR,
    FAILED_JOB_DIR
)


class JobRepository:

    @staticmethod
    def generate_job_id():

        date_str = datetime.now().strftime(
            "%Y%m%d"
        )

        existing_jobs = []

        for folder in [
            ACTIVE_JOB_DIR,
            COMPLETED_JOB_DIR,
            FAILED_JOB_DIR
        ]:

            os.makedirs(
                folder,
                exist_ok=True
            )

            existing_jobs.extend(
                os.listdir(folder)
            )

        sequence = len(existing_jobs) + 1

        return (
            f"EXT_{date_str}_"
            f"{sequence:03d}"
        )

    @staticmethod
    def create_job(subject):

        job_id = (
            JobRepository.generate_job_id()
        )

        job_data = {
            "job_id": job_id,
            "job_type": "extraction",
            "subject": subject,
            "status": "RUNNING",
            "started_at": (
                datetime.now().isoformat()
            ),
            "processed": 0,
            "successful": 0,
            "failed": 0
        }

        filepath = os.path.join(
            ACTIVE_JOB_DIR,
            f"{job_id}.json"
        )

        with open(
            filepath,
            "w",
            encoding="utf-8"
        ) as f:

            json.dump(
                job_data,
                f,
                indent=2
            )

        return job_data

    @staticmethod
    def update_job(
        job_id,
        data
    ):

        filepath = os.path.join(
            ACTIVE_JOB_DIR,
            f"{job_id}.json"
        )

        with open(
            filepath,
            "w",
            encoding="utf-8"
        ) as f:

            json.dump(
                data,
                f,
                indent=2
            )

    @staticmethod
    def complete_job(
        job_data
    ):

        job_id = job_data["job_id"]

        source_file = os.path.join(
            ACTIVE_JOB_DIR,
            f"{job_id}.json"
        )

        target_file = os.path.join(
            COMPLETED_JOB_DIR,
            f"{job_id}.json"
        )

        job_data["status"] = "COMPLETED"

        job_data["completed_at"] = (
            datetime.now().isoformat()
        )

        with open(
            target_file,
            "w",
            encoding="utf-8"
        ) as f:

            json.dump(
                job_data,
                f,
                indent=2
            )

        if os.path.exists(source_file):
            os.remove(source_file)

    @staticmethod
    def fail_job(
        job_data
    ):

        job_id = job_data["job_id"]

        source_file = os.path.join(
            ACTIVE_JOB_DIR,
            f"{job_id}.json"
        )

        target_file = os.path.join(
            FAILED_JOB_DIR,
            f"{job_id}.json"
        )

        job_data["status"] = "FAILED"

        with open(
            target_file,
            "w",
            encoding="utf-8"
        ) as f:

            json.dump(
                job_data,
                f,
                indent=2
            )

        if os.path.exists(source_file):
            os.remove(source_file)