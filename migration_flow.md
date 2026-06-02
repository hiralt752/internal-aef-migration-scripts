# Extraction Migration Flow

## Command

Extraction is executed using:

```bash
python migration.py extraction
```

---

# High Level Flow

```text
migration.py
    ↓
MigrationPipeline
    ↓
ExtractionProcessor
    ↓
Read CSV Files
    ↓
Extract Question IDs
    ↓
Remove Duplicates
    ↓
Resume Check
    ↓
Batch Processing
    ↓
QuestionFetcher
    ↓
SourceClient
    ↓
Question API
    ↓
Save Responses
    ↓
Generate Logs
    ↓
Generate Reports
    ↓
Complete Job
```

---

# Detailed Flow

## Step 1 – Application Startup

Command:

```bash
python migration.py extraction
```

The application validates:

* Command argument
* Environment variables
* Folder structure

Required:

```text
.env
storage/
```

---

## Step 2 – Bootstrap

Required folders are created automatically.

Example:

```text
storage/raw/extracted/
storage/jobs/
storage/reports/
storage/logs/
```

---

## Step 3 – Pipeline Execution

The migration pipeline receives:

```text
extraction
```

and starts:

```python
ExtractionProcessor
```

---

## Step 4 – CSV Discovery

The project scans:

```text
storage/input/csv/
```

Example:

```text
Arabic.csv
Biology.csv
```

Each CSV is processed independently.

---

## Step 5 – Job Creation

A new job record is created.

Example:

```json
{
  "job_id": "EXT_20260602_001",
  "status": "RUNNING"
}
```

Stored in:

```text
storage/jobs/active/
```

---

## Step 6 – Read Question IDs

The CSV is loaded.

Example:

```csv
Question Id
123
124
125
123
```

Question IDs are extracted.

---

## Step 7 – Duplicate Removal

Duplicate Question IDs are removed.

Example:

Before:

```text
123
124
125
123
```

After:

```text
123
124
125
```

The duplicate count is recorded for reporting.

---

## Step 8 – Resume Check

The system checks:

```text
success_question_log.csv
```

and determines previously processed Question IDs.

Already processed IDs are skipped.

Only remaining IDs continue.

---

## Step 9 – Batch Creation

Question IDs are processed in batches.

Current configuration:

```python
BATCH_SIZE = 500
```

Maximum recommended value:

```python
500
```

Larger batches previously caused API instability.

---

## Step 10 – Concurrent API Requests

QuestionFetcher creates concurrent requests.

Current configuration:

```python
CONCURRENT_REQUESTS = 50
```

Each Question ID generates:

```text
GET /questions/{question_id}
```

---

## Step 11 – Retry Processing

Retryable responses:

* 429
* 500
* 502
* 503
* 504

Retry mechanism:

* Exponential backoff
* Random jitter

Maximum retries:

```python
MAX_RETRIES = 5
```

---

## Step 12 – Save Results

Successful responses:

```json
{
  "question_id": "123",
  "status_code": 200,
  "response": {}
}
```

are added to:

```text
all_questions.json
```

---

## Step 13 – Periodic Backup

Every:

```python
SAVE_EVERY = 1000
```

records:

* Partial JSON backup is saved.
* Success log is saved.
* Failure log is saved.

This prevents data loss.

---

## Step 14 – Emergency Backup

If extraction stops unexpectedly:

* Partial files remain available.
* Resume information remains available.

---

## Step 15 – Report Generation

After completion:

```json
{
  "total_records": 1000,
  "unique_records": 950,
  "duplicate_records": 50,
  "successful": 945,
  "failed": 5
}
```

is generated.

Stored in:

```text
storage/reports/job_reports/
```

---

## Step 16 – Job Completion

Job status changes:

```json
{
  "status": "COMPLETED"
}
```

Job file moves to:

```text
storage/jobs/completed/
```

---

# Output Structure

Example:

```text
storage/raw/extracted/

└── Arabic/

    ├── all_questions.json
    ├── all_questions_partial.json

    ├── success_question_log.csv
    ├── failure_question_log.csv

    └── extraction_metadata.json
```

---

# Resume Example

Suppose:

```text
15000 unique Question IDs
```

Processing stops at:

```text
8500
```

Next execution:

```bash
python migration.py extraction
```

The project:

* Reads success logs
* Determines completed Question IDs
* Skips processed records
* Continues from remaining records

No duplicate API calls occur.

---

# Completed Subject Example

If:

```json
{
  "status": "COMPLETED"
}
```

exists in:

```text
extraction_metadata.json
```

the subject is skipped automatically.

Example:

```text
Arabic -> Skipped
Biology -> Processing
```

This prevents unnecessary extraction and API usage.
