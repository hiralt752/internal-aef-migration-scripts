import os
import json
import asyncio
import time
import re
from datetime import datetime
from collections import defaultdict

from base_api_client import BaseApiClient


ENDPOINT = "https://shared.alefed.com/question-bank-service/api/v1/questions"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BASE_DIR)

INPUT_DIR = os.path.join(PROJECT_ROOT, "transformation_engine", "transformation_output")
REPORT_DIR = os.path.join(BASE_DIR, "api_reports")

MAX_CONCURRENT_REQUESTS = 10
WORKERS = min(32, os.cpu_count() or 4)


class Logger:
    @staticmethod
    def info(msg): print(f"[INFO] {msg}")

    @staticmethod
    def success(msg): print(f"[SUCCESS] {msg}")

    @staticmethod
    def error(msg): print(f"[ERROR] {msg}")

class GlobalConcurrencyLimiter:
    """
    Allows up to `max_concurrent` API calls to be in-flight
    at the same time, across all workers.
    """
    def __init__(self, max_concurrent: int):
        self.semaphore = asyncio.Semaphore(max_concurrent)

    async def __aenter__(self):
        await self.semaphore.acquire()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        self.semaphore.release()

def discover_files():
    files = []
    for root, _, filenames in os.walk(INPUT_DIR):
        for f in filenames:
            if f.endswith(".json"):
                files.append(os.path.join(root, f))
    return files


def load_payloads(file_path):
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else [data]
    except Exception as e:
        Logger.error(f"Failed loading {file_path}: {e}")
        return []

def load_processed_question_ids():
    processed_ids = set()

    if not os.path.exists(REPORT_DIR):
        return processed_ids

    for file_name in os.listdir(REPORT_DIR):
        if not file_name.endswith(".json"):
            continue

        file_path = os.path.join(REPORT_DIR, file_name)

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            if isinstance(data, list):
                for item in data:
                    qid = item.get("question_id")
                    if qid:
                        processed_ids.add(qid)

        except Exception:
            continue

    Logger.info(f"Loaded {len(processed_ids)} already processed question IDs")
    return processed_ids

class GlobalMetrics:
    def __init__(self):
        self.lock = asyncio.Lock()
        self.total = 0
        self.success = 0
        self.failed = 0
        self.failed_ids = []

    async def add_success(self):
        async with self.lock:
            self.total += 1
            self.success += 1

    async def add_failure(self, question_id):
        async with self.lock:
            self.total += 1
            self.failed += 1
            self.failed_ids.append(question_id)

    def save_failed_ids(self, path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.failed_ids, f, indent=2)

    def print_summary(self, duration):
        print("\n================ PIPELINE SUMMARY ================\n")
        print(f"Total Payloads : {self.total}")
        print(f"Success        : {self.success}")
        print(f"Failed         : {self.failed}")
        if self.total:
            print(f"Success Rate   : {(self.success/self.total)*100:.2f}%")
        else:
            print("Success Rate   : N/A (no payloads processed)")
        print(f"Time Taken     : {duration:.2f} seconds")
        print("\n=================================================\n")

class ReportFileLocks:
    def __init__(self):
        self._locks = defaultdict(asyncio.Lock)
        self._meta_lock = asyncio.Lock()

    async def get_lock(self, status_code):
        async with self._meta_lock:
            return self._locks[status_code]

class ApiWorker:

    def __init__(self, worker_id, concurrency_limiter, metrics, report_locks):
        self.worker_id = worker_id
        self.concurrency_limiter = concurrency_limiter
        self.metrics = metrics
        self.report_locks = report_locks
        self.client = BaseApiClient()

    async def process_queue(self, queue: asyncio.Queue):

        while True:
            item = await queue.get()

            if item is None:
                break

            file_path, payload = item
            await self._post(file_path, payload)

            queue.task_done()

    async def _store_by_status(
        self,
        status_code,
        question_id,
        question_type,
        response,
        timestamp
    ):
        file_path = os.path.join(REPORT_DIR, f"{status_code}.json")
        os.makedirs(REPORT_DIR, exist_ok=True)

        record = {
            "question_id": question_id,
            "question_type": question_type,
            "response": response,
            "timestamp": timestamp
        }

        lock = await self.report_locks.get_lock(status_code)

        async with lock:
            data = []

            if os.path.exists(file_path):
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                except Exception:
                    data = []

            data.append(record)

            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

    async def _post(self, file_path, payload):

        question_id = payload.get("metadata", {}).get("general", {}).get("externalId") or payload.get("question_id")
        question_type = payload.get("type")
        timestamp = datetime.now().isoformat()

        Logger.info(f"[Worker-{self.worker_id}] START | {question_id}")

        try:
            # Acquire one of the 5 concurrency slots before calling the API.
            async with self.concurrency_limiter:
                response = await self.client.post(ENDPOINT, payload=payload)

            status_code = getattr(response, "status_code", 200)

            try:
                response_body = response.json() if hasattr(response, "json") else response
            except Exception:
                response_body = str(response)

            Logger.success(
                f"[Worker-{self.worker_id}] SUCCESS | {question_id} | {status_code}"
            )

            await self.metrics.add_success()

            await self._store_by_status(
                status_code,
                question_id,
                question_type,
                response_body,
                timestamp
            )

        except Exception as e:

            Logger.error(
                f"[Worker-{self.worker_id}] FAIL | {question_id} | {str(e)}"
            )

            await self.metrics.add_failure(question_id)

            await self._store_by_status(
                500,
                question_id,
                question_type,
                str(e),
                timestamp
            )

    async def close(self):
        await self.client.close()

def split_files(files, workers):
    chunks = [[] for _ in range(workers)]
    for i, f in enumerate(files):
        chunks[i % workers].append(f)
    return chunks


async def worker_runner(worker_id, files, concurrency_limiter, metrics, report_locks, processed_ids):

    Logger.info(f"Worker {worker_id} started with {len(files)} files")

    worker = ApiWorker(worker_id, concurrency_limiter, metrics, report_locks)
    queue = asyncio.Queue()

    skipped = 0

    for file_path in files:
        payloads = load_payloads(file_path)

        for payload in payloads:

            question_id = payload.get("metadata", {}).get("general", {}).get("externalId")

            if question_id in processed_ids:
                skipped += 1
                Logger.info(f"[Worker-{worker_id}] SKIP | {question_id}")
                continue

            queue.put_nowait((file_path, payload))

    queue.put_nowait(None)

    consumer_task = asyncio.create_task(worker.process_queue(queue))
    await consumer_task

    await worker.close()

    Logger.success(
        f"Worker {worker_id} completed | skipped={skipped}"
    )

def run_pipeline():

    run_id = datetime.now().strftime("run_%Y_%m_%d_%H_%M_%S")
    start_time = time.time()

    files = discover_files()

    if not files:
        Logger.error("No files found")
        return

    Logger.info(f"Total files: {len(files)}")
    Logger.info(f"Workers: {WORKERS}")
    Logger.info(f"Max Concurrent API Calls: {MAX_CONCURRENT_REQUESTS}")

    concurrency_limiter = GlobalConcurrencyLimiter(MAX_CONCURRENT_REQUESTS)
    metrics = GlobalMetrics()
    report_locks = ReportFileLocks()

    processed_ids = load_processed_question_ids()

    file_chunks = split_files(files, WORKERS)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    tasks = [
        worker_runner(
            i,
            file_chunks[i],
            concurrency_limiter,
            metrics,
            report_locks,
            processed_ids
        )
        for i in range(WORKERS)
    ]

    loop.run_until_complete(asyncio.gather(*tasks))

    duration = time.time() - start_time

    failed_file = os.path.join(REPORT_DIR, run_id, "failed_question_ids.json")
    metrics.save_failed_ids(failed_file)

    metrics.print_summary(duration)

    Logger.success(f"FAILED IDS SAVED -> {failed_file}")
    Logger.success("PIPELINE COMPLETE")

if __name__ == "__main__":
    run_pipeline()