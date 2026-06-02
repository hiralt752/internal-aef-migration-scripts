import os

from config.settings import (
    CSV_INPUT_DIR,
    RAW_EXTRACTION_DIR,
    FAILED_EXTRACTION_DIR,
    ACTIVE_JOB_DIR,
    COMPLETED_JOB_DIR,
    FAILED_JOB_DIR,
    REPORT_DIR,
    APPLICATION_LOG_DIR,
    API_LOG_DIR,
    ERROR_LOG_DIR
)


def bootstrap_storage():

    directories = [

        CSV_INPUT_DIR,

        RAW_EXTRACTION_DIR,

        FAILED_EXTRACTION_DIR,

        ACTIVE_JOB_DIR,
        COMPLETED_JOB_DIR,
        FAILED_JOB_DIR,

        REPORT_DIR,

        APPLICATION_LOG_DIR,
        API_LOG_DIR,
        ERROR_LOG_DIR
    ]

    for directory in directories:

        os.makedirs(
            directory,
            exist_ok=True
        )