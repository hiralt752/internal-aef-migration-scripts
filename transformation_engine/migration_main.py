import os
import json
import asyncio
import time
import re
from datetime import datetime
from collections import defaultdict

from base_api_client import BaseApiClient


# ============================================================
# CONFIG
# ============================================================
ENDPOINT = "https://ccl-rc-az.nprd.alefed.com/question-bank-service/api/v1/questions"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BASE_DIR)

INPUT_DIR = os.path.join(PROJECT_ROOT, "transformation_engine", "transformation_output")
REPORT_DIR = os.path.join(BASE_DIR, "api_reports")

GLOBAL_RATE_LIMIT_SECONDS = 1
WORKERS = min(32, os.cpu_count() or 4)


# ============================================================
# LOGGER
# ============================================================
class Logger:
    @staticmethod
    def info(msg): print(f"[INFO] {msg}")

    @staticmethod
    def success(msg): print(f"[SUCCESS] {msg}")

    @staticmethod
    def error(msg): print(f"[ERROR] {msg}")


# ============================================================
# RATE LIMITER
# ============================================================
class GlobalRateLimiter:
    def __init__(self, delay_seconds: float):
        self.delay = delay_seconds
        self.lock = asyncio.Lock()
        self.last_call = 0

    async def wait(self):
        async with self.lock:
            now = time.time()
            wait_time = self.delay - (now - self.last_call)

            if wait_time > 0:
                await asyncio.sleep(wait_time)

            self.last_call = time.time()


# ============================================================
# FILE LOADER
# ============================================================
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


# ============================================================
# SHARED METRICS STORE
# ============================================================
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
        print(f"Success Rate   : {(self.success/self.total)*100:.2f}%")
        print(f"Time Taken     : {duration:.2f} seconds")
        print("\n=================================================\n")


# ============================================================
# API WORKER
# ============================================================
class ApiWorker:

    def __init__(self, worker_id, rate_limiter, metrics):
        self.worker_id = worker_id
        self.rate_limiter = rate_limiter
        self.metrics = metrics
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

        question_id = payload.get("metadata", {}).get("general", {}).get("externalId")
        question_type = payload.get("type")
        timestamp = datetime.now().isoformat()

        Logger.info(f"[Worker-{self.worker_id}] START | {question_id}")

        try:
            await self.rate_limiter.wait()

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

            # STORE SUCCESS/FAIL RESPONSE
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

            # store exception as 500 bucket
            await self._store_by_status(
                500,
                question_id,
                question_type,
                str(e),
                timestamp
            )

    async def close(self):
        await self.client.close()


# ============================================================
# PIPELINE
# ============================================================
def split_files(files, workers):
    chunks = [[] for _ in range(workers)]
    for i, f in enumerate(files):
        chunks[i % workers].append(f)
    return chunks


async def worker_runner(worker_id, files, rate_limiter, metrics):

    Logger.info(f"Worker {worker_id} started with {len(files)} files")

    worker = ApiWorker(worker_id, rate_limiter, metrics)
    queue = asyncio.Queue()

    for file_path in files:
        payloads = load_payloads(file_path)
        for payload in payloads:
            await queue.put((file_path, payload))

    for _ in range(WORKERS):
        await queue.put(None)

    consumer_task = asyncio.create_task(worker.process_queue(queue))
    await consumer_task

    await worker.close()

    Logger.success(f"Worker {worker_id} completed")


# ============================================================
# RUN PIPELINE
# ============================================================
def run_pipeline():

    run_id = datetime.now().strftime("run_%Y_%m_%d_%H_%M_%S")

    start_time = time.time()

    files = discover_files()

    if not files:
        Logger.error("No files found")
        return

    Logger.info(f"Total files: {len(files)}")
    Logger.info(f"Workers: {WORKERS}")
    Logger.info(f"Rate Limit: {GLOBAL_RATE_LIMIT_SECONDS}s")

    rate_limiter = GlobalRateLimiter(GLOBAL_RATE_LIMIT_SECONDS)
    metrics = GlobalMetrics()

    file_chunks = split_files(files, WORKERS)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    tasks = [
        worker_runner(i, file_chunks[i], rate_limiter, metrics)
        for i in range(WORKERS)
    ]

    loop.run_until_complete(asyncio.gather(*tasks))

    end_time = time.time()
    duration = end_time - start_time

    # ========================================================
    # KEEP EXISTING FAILED IDS FILE
    # ========================================================
    failed_file = os.path.join(REPORT_DIR, run_id, "failed_question_ids.json")
    metrics.save_failed_ids(failed_file)

    # ========================================================
    # SUMMARY
    # ========================================================
    metrics.print_summary(duration)

    Logger.success(f"FAILED IDS SAVED -> {failed_file}")
    Logger.success("PIPELINE COMPLETE")


# ============================================================
if __name__ == "__main__":
    run_pipeline()