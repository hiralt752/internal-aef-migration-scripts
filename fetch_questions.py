import os
import json
import asyncio
import random
from collections import Counter

import pandas as pd
import aiohttp
import aiofiles
from tqdm.asyncio import tqdm
from dotenv import load_dotenv

# ======================================================
# LOAD ENV VARIABLES
# ======================================================

load_dotenv()

# ======================================================
# CONFIGURATION
# ======================================================

"""
========================================================
QUESTION FETCHING SCRIPT
========================================================

This script:

1. Reads all CSV files from current folder
2. Extracts Question IDs
3. Removes duplicate Question IDs
4. Fetches question data from API
5. Saves:
    - all_questions.json
    - success_question_log.csv
    - failure_question_log.csv

IMPORTANT:
- Keep CSV files in same folder
- Add Bearer Token in .env file

========================================================
"""

INPUT_FOLDER = "."
OUTPUT_FOLDER = "output"

BASE_URL = (
    "https://shared.alefed.com/"
    "assessment-question-service/api/questions/{}"
)

# ======================================================
# AUTHORIZATION
# ======================================================

BEARER_TOKEN = os.getenv("BEARER_TOKEN")

if not BEARER_TOKEN:

    raise ValueError(
        "BEARER_TOKEN missing in .env file"
    )

HEADERS = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {BEARER_TOKEN}"
}

# ======================================================
# PERFORMANCE SETTINGS
# ======================================================

"""
IMPORTANT:

Do not increase concurrency aggressively.

High concurrency can overload API gateway
and produce 503 errors.

Recommended safe range:
25 to 75
"""

CONCURRENT_REQUESTS = 50

SAVE_EVERY = 1000

BATCH_SIZE = 500

MAX_RETRIES = 5

# ======================================================
# CREATE OUTPUT FOLDER
# ======================================================

os.makedirs(OUTPUT_FOLDER, exist_ok=True)

# ======================================================
# FIND CSV FILES
# ======================================================

csv_files = [
    file for file in os.listdir(INPUT_FOLDER)
    if file.endswith(".csv")
]

print(f"\nFound {len(csv_files)} CSV files")

# ======================================================
# SEMAPHORE
# ======================================================

semaphore = asyncio.Semaphore(
    CONCURRENT_REQUESTS
)

# ======================================================
# SAVE JSON
# ======================================================

async def save_json(
    filepath,
    data
):
    """
    Save data into JSON file.
    """

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
# SAVE CSV LOG
# ======================================================

def save_log_csv(
    filepath,
    records
):
    """
    Save logs into CSV file.
    """

    df = pd.DataFrame(records)

    df.to_csv(
        filepath,
        index=False,
        encoding="utf-8"
    )

# ======================================================
# FETCH QUESTION
# ======================================================

async def fetch_question(
    session,
    question_id
):
    """
    Fetch single question from API.

    Includes:
    - Retry handling
    - Exponential backoff
    - Random jitter
    - Safe failure handling
    """

    url = BASE_URL.format(question_id)

    async with semaphore:

        for attempt in range(MAX_RETRIES):

            try:

                async with session.get(
                    url,
                    headers=HEADERS
                ) as response:

                    status = response.status

                    try:
                        data = await response.json()

                    except Exception:
                        data = await response.text()

                    # ==================================
                    # SUCCESS
                    # ==================================

                    if status == 200:

                        return {
                            "question_id": question_id,
                            "status_code": status,
                            "response": data
                        }

                    # ==================================
                    # RETRYABLE STATUS
                    # ==================================

                    if status in [
                        429,
                        500,
                        502,
                        503,
                        504
                    ]:

                        wait_time = (
                            (2 ** attempt)
                            + random.uniform(0.5, 2)
                        )

                        print(
                            f"Retrying {question_id} | "
                            f"Status: {status} | "
                            f"Attempt: {attempt + 1} | "
                            f"Waiting: {wait_time:.2f}s"
                        )

                        await asyncio.sleep(wait_time)

                        continue

                    # ==================================
                    # NON-RETRYABLE FAILURE
                    # ==================================

                    return {
                        "question_id": question_id,
                        "status_code": status,
                        "response": data,
                        "error": f"HTTP {status}"
                    }

            except Exception as e:

                wait_time = (
                    (2 ** attempt)
                    + random.uniform(0.5, 2)
                )

                print(
                    f"\nException for {question_id} | "
                    f"Attempt: {attempt + 1} | "
                    f"Waiting: {wait_time:.2f}s"
                )

                await asyncio.sleep(wait_time)

        # ==============================================
        # FINAL FAILURE AFTER ALL RETRIES
        # ==============================================

        return {
            "question_id": question_id,
            "status_code": None,
            "error": (
                f"Failed after "
                f"{MAX_RETRIES} retries"
            )
        }

# ======================================================
# PROCESS SUBJECT
# ======================================================

async def process_subject(
    session,
    csv_file
):
    """
    Process one CSV subject file.
    """

    subject_name = os.path.splitext(
        csv_file
    )[0]

    print(f"\n================================================")
    print(f"Processing Subject: {subject_name}")
    print(f"================================================")

    # ==================================================
    # CREATE OUTPUT FOLDER
    # ==================================================

    subject_output_folder = os.path.join(
        OUTPUT_FOLDER,
        subject_name
    )

    os.makedirs(
        subject_output_folder,
        exist_ok=True
    )

    # ==================================================
    # STORAGE
    # ==================================================

    all_responses = []

    success_logs = []

    failure_logs = []

    # ==================================================
    # READ CSV
    # ==================================================

    try:

        df = pd.read_csv(
            csv_file,
            encoding="utf-16",
            sep="\t"
        )

    except Exception as e:

        print(f"Failed reading {csv_file}: {e}")

        return

    # ==================================================
    # CLEAN COLUMNS
    # ==================================================

    df.columns = df.columns.str.strip()

    if "Question Id" not in df.columns:

        print(
            f"'Question Id' column missing "
            f"in {csv_file}"
        )

        return

    # ==================================================
    # EXTRACT IDS
    # ==================================================

    question_ids = (
        df["Question Id"]
        .dropna()
        .astype(str)
        .tolist()
    )

    # ==================================================
    # COUNT DUPLICATES
    # ==================================================

    question_counter = Counter(
        question_ids
    )

    unique_question_ids = list(
        question_counter.keys()
    )

    total_questions = len(
        unique_question_ids
    )

    print(
        f"Total Unique Questions: "
        f"{total_questions}"
    )

    counter = 0

    # ==================================================
    # PROCESS BATCHES
    # ==================================================

    try:

        for batch_start in range(
            0,
            total_questions,
            BATCH_SIZE
        ):

            batch_end = min(
                batch_start + BATCH_SIZE,
                total_questions
            )

            batch_question_ids = (
                unique_question_ids[
                    batch_start:batch_end
                ]
            )

            print(
                f"\n[{subject_name}] "
                f"Processing Batch "
                f"{batch_start} -> {batch_end}"
            )

            tasks = [
                fetch_question(
                    session,
                    qid
                )
                for qid in batch_question_ids
            ]

            for future in tqdm.as_completed(
                tasks,
                desc=f"{subject_name} Batch"
            ):

                result = await future

                if not result:
                    continue

                all_responses.append(result)

                counter += 1

                question_id = result.get(
                    "question_id"
                )

                repeat_count = (
                    question_counter.get(
                        question_id,
                        1
                    )
                )

                # ======================================
                # SUCCESS
                # ======================================

                if (
                    result.get("status_code")
                    == 200
                    and "error" not in result
                ):

                    success_logs.append({
                        "question_id": question_id,
                        "subject": subject_name,
                        "status": "success",
                        "number_of_repeats": (
                            repeat_count
                        )
                    })

                # ======================================
                # FAILURE
                # ======================================

                else:

                    failure_logs.append({
                        "question_id": question_id,
                        "subject": subject_name,
                        "status": "failure",
                        "number_of_repeats": (
                            repeat_count
                        )
                    })

                # ======================================
                # PERIODIC SAVE
                # ======================================

                if counter % SAVE_EVERY == 0:

                    print(
                        f"\n[{subject_name}] "
                        f"Saving partial files..."
                    )

                    await save_json(
                        os.path.join(
                            subject_output_folder,
                            "all_questions_partial.json"
                        ),
                        all_responses
                    )

                    save_log_csv(
                        os.path.join(
                            subject_output_folder,
                            "success_question_log.csv"
                        ),
                        success_logs
                    )

                    save_log_csv(
                        os.path.join(
                            subject_output_folder,
                            "failure_question_log.csv"
                        ),
                        failure_logs
                    )

    finally:

        # ==============================================
        # ALWAYS SAVE EMERGENCY BACKUP
        # ==============================================

        print(
            f"\n[{subject_name}] "
            f"Saving emergency backup files..."
        )

        await save_json(
            os.path.join(
                subject_output_folder,
                "all_questions_partial.json"
            ),
            all_responses
        )

        save_log_csv(
            os.path.join(
                subject_output_folder,
                "success_question_log.csv"
            ),
            success_logs
        )

        save_log_csv(
            os.path.join(
                subject_output_folder,
                "failure_question_log.csv"
            ),
            failure_logs
        )

    # ==================================================
    # FINAL SAVE
    # ==================================================

    print(
        f"\n[{subject_name}] "
        f"Saving final files..."
    )

    await save_json(
        os.path.join(
            subject_output_folder,
            "all_questions.json"
        ),
        all_responses
    )

    # ==================================================
    # COMPLETED
    # ==================================================

    print(f"\nCompleted: {subject_name}")

    print(
        "\nYou can now safely delete "
        "'all_questions_partial.json' "
        "file if not needed.\n"
    )

# ======================================================
# MAIN
# ======================================================

async def main():
    """
    Main execution function.
    """

    connector = aiohttp.TCPConnector(
        limit=CONCURRENT_REQUESTS,
        ssl=False,
        force_close=True
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
# ENTRY POINT
# ======================================================

if __name__ == "__main__":

    asyncio.run(main())