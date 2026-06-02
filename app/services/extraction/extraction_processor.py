import os
import asyncio

from config.constants import (
    BATCH_SIZE,
    SAVE_EVERY
)

from config.logging_config import (
    get_extraction_logger
)

from config.settings import (
    CSV_INPUT_DIR,
    RAW_EXTRACTION_DIR
)

from repositories.job_repository import (
    JobRepository
)

from repositories.report_repository import (
    ReportRepository
)

from services.extraction.question_fetcher import (
    QuestionFetcher
)

from utils.csv_utils import (
    read_question_ids,
    build_question_stats
)

from utils.file_utils import (
    create_directory,
    save_json,
    save_csv
)
from services.pipeline.resume_processor import (
    ResumeProcessor
)

from utils.metadata_utils import (
    save_metadata,
    load_metadata
)

logger = get_extraction_logger()


class ExtractionProcessor:

    def __init__(self):

        self.fetcher = (
            QuestionFetcher()
        )

    async def process_subject(
        self,
        csv_file
    ):

        subject_name = (
            os.path.splitext(
                csv_file
            )[0]
        )

        logger.info(
            f"Started subject: "
            f"{subject_name}"
        )

        job_data = (
            JobRepository
            .create_job(
                subject_name
            )
        )

        job_id = (
            job_data["job_id"]
        )

        subject_output_dir = (
            os.path.join(
                RAW_EXTRACTION_DIR,
                subject_name
            )
        )

        metadata_file = os.path.join(
            subject_output_dir,
            "extraction_metadata.json"
        )

        create_directory(
            subject_output_dir
        )

        existing_metadata = (
            load_metadata(
                metadata_file
            )
        )

        if (
            existing_metadata
            and
            existing_metadata.get(
                "status"
            )
            == "COMPLETED"
        ):

            logger.info(
                f"{subject_name} "
                f"already extracted. "
                f"Skipping."
            )

            return

        csv_path = os.path.join(
            CSV_INPUT_DIR,
            csv_file
        )

        # ==================================
        # READ CSV
        # ==================================

        question_ids = (
            read_question_ids(
                csv_path
            )
        )

        (
            unique_question_ids,
            question_counter,
            total_count,
            unique_count,
            duplicate_count
        ) = build_question_stats(
            question_ids
        )

        (
            unique_question_ids,
            already_processed
        ) = (
            ResumeProcessor
            .get_remaining_question_ids(
                subject_output_dir,
                unique_question_ids
            )
        )

        logger.info(
            f"{subject_name} "
            f"Already Processed: "
            f"{already_processed}"
        )

        logger.info(
            f"{subject_name} | "
            f"Total={total_count} | "
            f"Unique={unique_count} | "
            f"Duplicates={duplicate_count}"
        )

        # ==================================
        # STORAGE
        # ==================================

        all_responses = []

        success_logs = []

        failure_logs = []

        processed_counter = 0

        try:

            # ==============================
            # BATCH PROCESSING
            # ==============================

            for batch_start in range(
                0,
                unique_count,
                BATCH_SIZE
            ):

                batch_end = min(
                    batch_start +
                    BATCH_SIZE,
                    unique_count
                )

                batch_ids = (
                    unique_question_ids[
                        batch_start:
                        batch_end
                    ]
                )

                logger.info(
                    f"{subject_name} "
                    f"Batch "
                    f"{batch_start}"
                    f" -> "
                    f"{batch_end}"
                )

                batch_results = (
                    await self.fetcher
                    .fetch_questions(
                        batch_ids,
                        subject_name
                    )
                )

                for result in (
                    batch_results
                ):

                    all_responses.append(
                        result
                    )

                    processed_counter += 1

                    question_id = (
                        result.get(
                            "question_id"
                        )
                    )

                    repeat_count = (
                        question_counter
                        .get(
                            question_id,
                            1
                        )
                    )

                    # ======================
                    # SUCCESS
                    # ======================

                    if (
                        result.get(
                            "status_code"
                        )
                        == 200
                        and
                        "error"
                        not in result
                    ):

                        success_logs.append(
                            {
                                "question_id":
                                    question_id,
                                "subject":
                                    subject_name,
                                "status":
                                    "success",
                                "number_of_repeats":
                                    repeat_count
                            }
                        )

                    else:

                        failure_logs.append(
                            {
                                "question_id":
                                    question_id,
                                "subject":
                                    subject_name,
                                "status":
                                    "failure",
                                "number_of_repeats":
                                    repeat_count
                            }
                        )

                    # ======================
                    # PERIODIC SAVE
                    # ======================

                    if (
                        processed_counter %
                        SAVE_EVERY
                        == 0
                    ):

                        logger.info(
                            f"{subject_name} "
                            f"Partial save"
                        )

                        await save_json(
                            os.path.join(
                                subject_output_dir,
                                "all_questions_partial.json"
                            ),
                            all_responses
                        )

                        save_csv(
                            os.path.join(
                                subject_output_dir,
                                "success_question_log.csv"
                            ),
                            success_logs
                        )

                        save_csv(
                            os.path.join(
                                subject_output_dir,
                                "failure_question_log.csv"
                            ),
                            failure_logs
                        )

                        job_data[
                            "processed"
                        ] = (
                            processed_counter
                        )

                        job_data[
                            "successful"
                        ] = (
                            len(
                                success_logs
                            )
                        )

                        job_data[
                            "failed"
                        ] = (
                            len(
                                failure_logs
                            )
                        )

                        JobRepository.update_job(
                            job_id,
                            job_data
                        )

        except KeyboardInterrupt:

            logger.error(
                f"{subject_name} "
                f"interrupted by user."
            )

            metadata = {
                "subject": subject_name,
                "status": "INTERRUPTED",
                "processed": processed_counter,
                "successful": len(
                    success_logs
                ),
                "failed": len(
                    failure_logs
                ),
                "job_id": job_id
            }

            save_metadata(
                metadata_file,
                metadata
            )

            job_data["status"] = (
                "INTERRUPTED"
            )

            JobRepository.fail_job(
                job_data
            )

            raise

        except Exception:

            logger.exception(
                f"Extraction failed "
                f"for "
                f"{subject_name}"
            )

            metadata = {
                "subject": subject_name,
                "status": "FAILED",
                "processed": processed_counter,
                "successful": len(
                    success_logs
                ),
                "failed": len(
                    failure_logs
                ),
                "job_id": job_id
            }

            save_metadata(
                metadata_file,
                metadata
            )

            JobRepository.fail_job(
                job_data
            )

            raise

        finally:

            # ==============================
            # EMERGENCY SAVE
            # ==============================

            logger.info(
                f"{subject_name} "
                f"Emergency backup"
            )

            await save_json(
                os.path.join(
                    subject_output_dir,
                    "all_questions_partial.json"
                ),
                all_responses
            )

            save_csv(
                os.path.join(
                    subject_output_dir,
                    "success_question_log.csv"
                ),
                success_logs
            )

            save_csv(
                os.path.join(
                    subject_output_dir,
                    "failure_question_log.csv"
                ),
                failure_logs
            )

        # ==================================
        # FINAL SAVE
        # ==================================

        await save_json(
            os.path.join(
                subject_output_dir,
                "all_questions.json"
            ),
            all_responses
        )

        # ==================================
        # REPORT
        # ==================================

        report = {
            "job_id": job_id,
            "job_type": "extraction",
            "subject": subject_name,
            "total_records":
                total_count,
            "unique_records":
                unique_count,
            "duplicate_records":
                duplicate_count,
            "successful":
                len(
                    success_logs
                ),
            "failed":
                len(
                    failure_logs
                )
        }

        ReportRepository.save_report(
            job_id,
            report
        )

        # ==================================
        # COMPLETE JOB
        # ==================================

        job_data[
            "processed"
        ] = (
            processed_counter
        )

        job_data[
            "successful"
        ] = (
            len(
                success_logs
            )
        )

        job_data[
            "failed"
        ] = (
            len(
                failure_logs
            )
        )

        metadata = {
            "subject": subject_name,
            "status": "COMPLETED",
            "processed": processed_counter,
            "successful": len(
                success_logs
            ),
            "failed": len(
                failure_logs
            ),
            "job_id": job_id
        }

        save_metadata(
            metadata_file,
            metadata
        )

        JobRepository.complete_job(
            job_data
        )

        logger.info(
            f"Completed "
            f"{subject_name}"
        )

    async def run(self):

        csv_files = [

            file

            for file
            in os.listdir(
                CSV_INPUT_DIR
            )

            if file.endswith(
                ".csv"
            )
        ]

        if not csv_files:

            raise ValueError(
                "No CSV files found in "
                f"{CSV_INPUT_DIR}"
            )

        logger.info(
            f"Found "
            f"{len(csv_files)} "
            f"CSV files"
        )

        for csv_file in (
            csv_files
        ):
            await self.process_subject(
                csv_file
            )