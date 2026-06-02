import logging
import os
from datetime import datetime

from config.settings import (
    APPLICATION_LOG_DIR
)


def get_extraction_logger():

    os.makedirs(
        APPLICATION_LOG_DIR,
        exist_ok=True
    )

    log_file = os.path.join(
        APPLICATION_LOG_DIR,
        f"extraction_{datetime.now():%Y%m%d}.log"
    )

    logger = logging.getLogger(
        "extraction"
    )

    logger.setLevel(logging.INFO)

    if logger.handlers:
        return logger

    formatter = logging.Formatter(
        "%(asctime)s | "
        "%(levelname)s | "
        "%(message)s"
    )

    file_handler = logging.FileHandler(
        log_file,
        encoding="utf-8"
    )

    file_handler.setFormatter(
        formatter
    )

    logger.addHandler(
        file_handler
    )

    return logger