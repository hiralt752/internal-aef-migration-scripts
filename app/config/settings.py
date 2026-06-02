import os

from dotenv import load_dotenv


APP_DIR = os.path.dirname(
    os.path.abspath(__file__)
)

APP_DIR = os.path.dirname(
    APP_DIR
)

REPO_DIR = os.path.dirname(
    APP_DIR
)

ENV_PATH = os.path.join(
    REPO_DIR,
    ".env"
)

load_dotenv(ENV_PATH)

# =====================================================
# API SETTINGS
# =====================================================

BEARER_TOKEN = os.getenv("BEARER_TOKEN")

if not BEARER_TOKEN:
    raise ValueError(
        "BEARER_TOKEN missing in .env file"
    )


SOURCE_BASE_URL = (
    "https://shared.alefed.com/"
    "assessment-question-service/api/questions/{}"
)


# =====================================================
# STORAGE PATHS
# =====================================================

BASE_DIR = os.path.dirname(
    os.path.abspath(__file__)
)

BASE_DIR = os.path.dirname(
    BASE_DIR
)

STORAGE_DIR = os.path.join(
    BASE_DIR,
    "storage"
)

CSV_INPUT_DIR = os.path.join(
    STORAGE_DIR,
    "input",
    "csv"
)

RAW_EXTRACTION_DIR = os.path.join(
    STORAGE_DIR,
    "raw",
    "extracted"
)

FAILED_EXTRACTION_DIR = os.path.join(
    STORAGE_DIR,
    "failed",
    "extraction_failures"
)

JOB_DIR = os.path.join(
    STORAGE_DIR,
    "jobs"
)

ACTIVE_JOB_DIR = os.path.join(
    JOB_DIR,
    "active"
)

COMPLETED_JOB_DIR = os.path.join(
    JOB_DIR,
    "completed"
)

FAILED_JOB_DIR = os.path.join(
    JOB_DIR,
    "failed"
)

REPORT_DIR = os.path.join(
    STORAGE_DIR,
    "reports",
    "job_reports"
)


# =====================================================
# LOGGING
# =====================================================

LOG_DIR = os.path.join(
    STORAGE_DIR,
    "logs"
)

APPLICATION_LOG_DIR = os.path.join(
    LOG_DIR,
    "application",
    "extraction"
)

API_LOG_DIR = os.path.join(
    LOG_DIR,
    "api"
)

ERROR_LOG_DIR = os.path.join(
    LOG_DIR,
    "error"
)