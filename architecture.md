# Migration project Architecture

## Overview

This project is a modular migration project designed to extract, process, transform, and upload assessment question data.

The project is designed around independent migration stages so that each stage can be executed separately without affecting previous stages.

Current implementation includes:

* Extraction Stage

Future stages:

* Structure Stage
* Transformation Stage
* Upload Stage

---

# Core Design Principles

## 1. Independent Stages

Each migration stage should be executable independently.

Example:

```bash
python migration.py extraction
```

Future:

```bash
python migration.py structure
python migration.py transformation
python migration.py upload
```

A stage should never re-run previous stages automatically.

---

## 2. Separation of Concerns

Each layer has a specific responsibility.

| Layer        | Responsibility             |
| ------------ | -------------------------- |
| migration.py | Entry point                |
| pipeline     | Orchestration              |
| services     | Business logic             |
| clients      | External API communication |
| repositories | Data persistence           |
| utils        | Shared utility functions   |
| storage      | Runtime generated files    |

---

## 3. Resume Support

Extraction jobs must be resumable.

If extraction is interrupted:

* Previously processed questions are not reprocessed.
* Extraction resumes from the remaining Question IDs.

---

## 4. Job Tracking

Every extraction execution generates a Job.

Example:

```json
{
  "job_id": "EXT_20260602_001",
  "status": "RUNNING"
}
```

Job states:

* RUNNING
* COMPLETED
* FAILED
* INTERRUPTED

---

## 5. Retry Support

Transient API failures are retried automatically using:

* Exponential backoff
* Random jitter

This helps prevent API overload and rate-limiting issues.

---

# Project Structure

```text
repo/

├── .env
├── .env.example
├── requirements.txt

└── app/

    ├── migration.py

    ├── config/
    │   ├── settings.py
    │   ├── constants.py
    │   └── logging_config.py

    ├── services/
    │   ├── extraction/
    │   └── pipeline/

    ├── clients/

    ├── repositories/

    ├── utils/

    └── storage/
```

---

# Configuration Layer

## settings.py

Responsible for:

* Loading environment variables
* Defining folder locations
* Defining application paths

Example:

```python
BEARER_TOKEN
CSV_INPUT_DIR
RAW_EXTRACTION_DIR
```

---

## constants.py

Contains runtime constants.

Examples:

```python
CONCURRENT_REQUESTS = 50
BATCH_SIZE = 500
SAVE_EVERY = 1000
MAX_RETRIES = 5
```

Important:

Batch size should not exceed 500.

Larger batches previously caused API instability.

---

## logging_config.py

Responsible only for logger configuration.

Examples:

```python
logger.info(...)
logger.error(...)
```

Log files are written to:

```text
storage/logs/
```

---

# Service Layer

The service layer contains business logic.

## ExtractionProcessor

Responsibilities:

* Read CSV files
* Process Question IDs
* Resume interrupted runs
* Call QuestionFetcher
* Save extraction outputs
* Generate reports
* Update job status

---

## QuestionFetcher

Responsibilities:

* Fetch question data
* Execute API requests
* Handle retry logic
* Handle concurrency limits

---

## ResumeProcessor

Responsibilities:

* Detect previously processed Question IDs
* Skip completed records
* Resume interrupted extraction jobs

---

# Client Layer

## SourceClient

Responsible for external API communication.

Example:

```text
https://shared.alefed.com/assessment-question-service/api/questions/{question_id}
```

No business logic should exist inside the client layer.

---

# Repository Layer

Repositories are responsible for persistence.

---

## JobRepository

Stores job metadata.

Examples:

```json
{
  "job_id": "EXT_20260602_001",
  "status": "RUNNING"
}
```

Locations:

```text
storage/jobs/active/
storage/jobs/completed/
storage/jobs/failed/
```

---

## ReportRepository

Stores extraction reports.

Example:

```json
{
  "total_records": 1000,
  "successful": 995,
  "failed": 5
}
```

Location:

```text
storage/reports/job_reports/
```

---

# Storage Architecture

## Input

```text
storage/input/csv/
```

Contains source CSV files.

Example:

```text
Arabic.csv
Biology.csv
```

---

## Raw Extraction Output

```text
storage/raw/extracted/
```

Contains extracted API responses.

---

## Failed Records

```text
storage/failed/
```

Stores failure-related artifacts.

---

## Reports

```text
storage/reports/
```

Stores job reports.

---

## Logs

```text
storage/logs/
```

Contains:

* application
* migration
* api
* error

---

# Resume Strategy

The project supports restart-safe extraction.

If extraction stops unexpectedly:

* Partial files remain available.
* Success logs remain available.
* Failure logs remain available.

Next execution:

```bash
python migration.py extraction
```

resumes only remaining Question IDs.

Already processed Question IDs are skipped.

---

# Metadata Tracking

Each subject maintains:

```text
extraction_metadata.json
```

Example:

```json
{
  "subject": "Arabic",
  "status": "COMPLETED"
}
```

Used to:

* Skip completed subjects
* Resume interrupted subjects
* Track extraction state

---

# Future Expansion

The architecture is intentionally designed to support:

* Structure processing
* Schema transformation
* Media migration
* Upload processing
* Retry processing
* Resume processing

without requiring major changes to the extraction layer.
