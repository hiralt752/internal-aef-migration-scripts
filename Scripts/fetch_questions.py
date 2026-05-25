"""
======================================================
Assessment Question API Fetcher
======================================================

Description:
------------
This script is used to fetch assessment question data
from the Alef Education Assessment Question API using
Question IDs stored inside multiple CSV files.

The script processes each CSV file subject-wise,
extracts unique Question IDs, sends asynchronous API
requests, and stores all responses in structured JSON
files.

The implementation is optimized for large-scale data
migration and supports:
    - Concurrent API requests
    - Retry mechanism
    - Batch processing
    - Partial progress saving
    - Failure tracking
    - Async file writing

------------------------------------------------------
Workflow:
------------------------------------------------------

1. Reads all CSV files from INPUT_FOLDER

2. For each CSV file:
    - Creates a dedicated output folder
    - Reads Question IDs from "Question Id" column
    - Removes duplicates and empty values

3. Processes Question IDs in batches

4. Sends asynchronous GET requests to:
       https://shared.alefed.com/
       assessment-question-service/api/questions/{id}

5. Stores:
    - Successful responses
    - Failed requests
    - Partial progress during execution

6. Saves final JSON outputs for each subject

------------------------------------------------------
Required Environment Variable:
------------------------------------------------------

ACCESS_TOKEN
    Bearer token used for API authorization.

Example:
    export ACCESS_TOKEN="your_token"

or on Windows:
    set ACCESS_TOKEN=your_token

------------------------------------------------------
Input:
------------------------------------------------------

Folder:
    INPUT_FOLDER

Expected Files:
    Multiple .csv files

Expected CSV Format:
    - UTF-16 encoded
    - Tab separated
    - Must contain column:
          "Question Id"

------------------------------------------------------
Configuration Parameters:
------------------------------------------------------

INPUT_FOLDER
    Directory containing input CSV files.

OUTPUT_FOLDER
    Root directory where output JSON files
    will be stored.

BASE_URL
    API endpoint template for fetching questions.

CONCURRENT_REQUESTS
    Maximum simultaneous API requests.

SAVE_EVERY
    Saves partial progress after every N records.

BATCH_SIZE
    Number of Question IDs processed per batch.

MAX_RETRIES
    Number of retries for temporary failures.

------------------------------------------------------
Output Structure:
------------------------------------------------------

output/
│
├── subject_name/
│   ├── all_questions.json
│   ├── failed_questions.json
│   └── all_questions_partial.json
│

------------------------------------------------------
Output Files:
------------------------------------------------------

1. all_questions.json
    Contains all API responses.

2. failed_questions.json
    Contains failed Question IDs with:
        - status_code
        - error details

3. all_questions_partial.json
    Intermediate checkpoint file saved periodically.

------------------------------------------------------
Response Format:
------------------------------------------------------

Successful Response:
{
    "question_id": "...",
    "status_code": 200,
    "response": {...}
}

Failed Response:
{
    "question_id": "...",
    "status_code": 500,
    "error": "..."
}

------------------------------------------------------
Libraries Used:
------------------------------------------------------

- asyncio
- aiohttp
- aiofiles
- pandas
- tqdm

------------------------------------------------------
Performance Notes:
------------------------------------------------------

- Uses asyncio for high-speed concurrent requests
- Uses semaphore to limit request overload
- Handles temporary server failures with retries
- Suitable for large datasets and migration pipelines

======================================================
"""


import os
import json
import asyncio
import pandas as pd
import aiohttp
import aiofiles
from tqdm.asyncio import tqdm

# ======================================================
# CONFIG
# ======================================================

INPUT_FOLDER = "."
OUTPUT_FOLDER = "output"

BASE_URL = (
    "https://shared.alefed.com/assessment-question-service/api/questions/{}"
)

HEADERS = {
    "Content-Type": "application/json",

    # Add token here
    "Authorization": f"Bearer {os.getenv("ACCESS_TOKEN")}"
}

# ======================================================
# PERFORMANCE CONFIG
# ======================================================

# Number of simultaneous API requests
CONCURRENT_REQUESTS = 200

# Save partial progress after every N records
SAVE_EVERY = 5000

# Process questions in chunks
BATCH_SIZE = 1000

# Retry failed requests
MAX_RETRIES = 3

# ======================================================
# CREATE OUTPUT ROOT
# ======================================================

os.makedirs(OUTPUT_FOLDER, exist_ok=True)

# ======================================================
# GET ALL CSV FILES
# ======================================================

csv_files = [
    file for file in os.listdir(INPUT_FOLDER)
    if file.endswith(".csv")
]

print(f"\nFound {len(csv_files)} CSV files")

# ======================================================
# SEMAPHORE
# ======================================================

semaphore = asyncio.Semaphore(CONCURRENT_REQUESTS)

# ======================================================
# FETCH QUESTION
# ======================================================

async def fetch_question(session, question_id):

    url = BASE_URL.format(question_id)

    async with semaphore:

        for attempt in range(MAX_RETRIES):

            try:

                async with session.get(
                    url,
                    headers=HEADERS,
                    timeout=60
                ) as response:

                    status = response.status

                    try:
                        data = await response.json()
                    except:
                        data = await response.text()

                    # Retry for temporary server issues
                    if status in [429, 500, 502, 503, 504]:

                        print(
                            f"Retrying {question_id} "
                            f"(Status: {status}) "
                            f"Attempt {attempt + 1}"
                        )

                        await asyncio.sleep(2)

                        continue

                    return {
                        "question_id": question_id,
                        "status_code": status,
                        "response": data
                    }

            except Exception as e:

                if attempt < MAX_RETRIES - 1:

                    await asyncio.sleep(2)

                else:

                    return {
                        "question_id": question_id,
                        "error": str(e)
                    }

# ======================================================
# SAVE JSON
# ======================================================

async def save_json(filepath, data):

    async with aiofiles.open(
        filepath,
        "w",
        encoding="utf-8"
    ) as f:

        await f.write(
            json.dumps(
                data,
                ensure_ascii=False,
                indent=2
            )
        )

# ======================================================
# PROCESS SINGLE SUBJECT FILE
# ======================================================

async def process_subject(session, csv_file):

    subject_name = os.path.splitext(csv_file)[0]

    print(f"\n================================================")
    print(f"Processing: {subject_name}")
    print(f"================================================")

    # --------------------------------------------------
    # CREATE SUBJECT FOLDER
    # --------------------------------------------------

    subject_output_folder = os.path.join(
        OUTPUT_FOLDER,
        subject_name
    )

    os.makedirs(subject_output_folder, exist_ok=True)

    # --------------------------------------------------
    # READ CSV
    # --------------------------------------------------

    try:

        df = pd.read_csv(
            csv_file,
            encoding="utf-16",
            sep="\t"
        )

    except Exception as e:

        print(f"Failed reading {csv_file}: {e}")
        return

    # --------------------------------------------------
    # CLEAN COLUMNS
    # --------------------------------------------------

    df.columns = df.columns.str.strip()

    # --------------------------------------------------
    # VALIDATE COLUMN
    # --------------------------------------------------

    if "Question Id" not in df.columns:

        print(f"'Question Id' column missing in {csv_file}")
        return

    # --------------------------------------------------
    # GET QUESTION IDS
    # --------------------------------------------------

    question_ids = (
        df["Question Id"]
        .dropna()
        .astype(str)
        .unique()
        .tolist()
    )

    total_questions = len(question_ids)

    print(f"Total Unique Question IDs: {total_questions}")

    # --------------------------------------------------
    # STORAGE
    # --------------------------------------------------

    all_responses = []
    failed_questions = []

    counter = 0

    # --------------------------------------------------
    # PROCESS IN BATCHES
    # --------------------------------------------------

    for batch_start in range(
        0,
        total_questions,
        BATCH_SIZE
    ):

        batch_end = min(
            batch_start + BATCH_SIZE,
            total_questions
        )

        batch_question_ids = question_ids[
            batch_start:batch_end
        ]

        print(
            f"\n[{subject_name}] "
            f"Processing Batch "
            f"{batch_start} -> {batch_end}"
        )

        # ----------------------------------------------
        # CREATE TASKS
        # ----------------------------------------------

        tasks = [
            fetch_question(session, qid)
            for qid in batch_question_ids
        ]

        # ----------------------------------------------
        # EXECUTE TASKS
        # ----------------------------------------------

        for future in tqdm.as_completed(
            tasks,
            desc=f"{subject_name} Batch"
        ):

            result = await future

            all_responses.append(result)

            counter += 1

            # ------------------------------------------
            # TRACK FAILURES
            # ------------------------------------------

            if (
                result.get("status_code") != 200
                or "error" in result
            ):

                failed_questions.append({
                    "question_id": result.get("question_id"),
                    "status_code": result.get("status_code"),
                    "error": result.get("error")
                })

            # ------------------------------------------
            # PERIODIC SAVE
            # ------------------------------------------

            if counter % SAVE_EVERY == 0:

                print(
                    f"\n[{subject_name}] "
                    f"Saving partial at {counter}"
                )

                await save_json(
                    os.path.join(
                        subject_output_folder,
                        "all_questions_partial.json"
                    ),
                    all_responses
                )

                await save_json(
                    os.path.join(
                        subject_output_folder,
                        "failed_questions.json"
                    ),
                    failed_questions
                )

    # ==================================================
    # FINAL SAVE
    # ==================================================

    print(f"\nSaving final files for {subject_name}")

    await save_json(
        os.path.join(
            subject_output_folder,
            "all_questions.json"
        ),
        all_responses
    )

    await save_json(
        os.path.join(
            subject_output_folder,
            "failed_questions.json"
        ),
        failed_questions
    )

    print(f"\nCompleted: {subject_name}")

# ======================================================
# MAIN
# ======================================================

async def main():

    connector = aiohttp.TCPConnector(
        limit=CONCURRENT_REQUESTS,
        ssl=False
    )

    timeout = aiohttp.ClientTimeout(
        total=None,
        sock_connect=60,
        sock_read=60
    )

    async with aiohttp.ClientSession(
        connector=connector,
        timeout=timeout
    ) as session:

        for csv_file in csv_files:

            await process_subject(
                session,
                csv_file
            )

# ======================================================
# RUN
# ======================================================

asyncio.run(main())