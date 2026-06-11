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

INPUT_DIR = r"D:\Alef_Final_Chapter\internal-aef-migration-scripts\transformation_engine\transformation_output"
REPORT_DIR = "api_reports"

GLOBAL_RATE_LIMIT_SECONDS = 1
WORKERS = min(32, os.cpu_count() or 4)


class Logger:
    @staticmethod
    def info(msg): print(f"[INFO] {msg}")

    @staticmethod
    def success(msg): print(f"[SUCCESS] {msg}")

    @staticmethod
    def error(msg): print(f"[ERROR] {msg}")


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


class ApiWorker:

    def __init__(self, worker_id, rate_limiter):
        self.worker_id = worker_id
        self.rate_limiter = rate_limiter
        self.client = BaseApiClient()

        self.results = defaultdict(list)
        self.file_stats = defaultdict(lambda: {"success": 0, "fail": 0})

    async def process_queue(self, queue: asyncio.Queue):

        while True:
            item = await queue.get()

            if item is None:
                break

            file_path, payload = item
            await self._post(file_path, payload)

            queue.task_done()

    async def _post(self, file_path, payload):

        question_id = payload.get("metadata", {}).get("general", {}).get("externalId")
        start_time = datetime.now().isoformat()

        Logger.info(
            f"[Worker-{self.worker_id}] START API | "
            f"file={os.path.basename(file_path)} | "
            f"question_id={question_id}"
        )

        try:
            await self.rate_limiter.wait()

            await self.client.post(ENDPOINT, payload=payload)

            Logger.success(
                f"[Worker-{self.worker_id}] SUCCESS | "
                f"question_id={question_id}"
            )

            self.results["SUCCESS"].append({
                "file": file_path,
                "questionId": question_id,
                "status": "SUCCESS",
                "timestamp": start_time
            })

            self.file_stats[file_path]["success"] += 1

        except Exception as e:

            status = self._extract_status(str(e))

            Logger.error(
                f"[Worker-{self.worker_id}] FAIL ({status}) | "
                f"question_id={question_id} | error={str(e)}"
            )

            self.results[status].append({
                "file": file_path,
                "questionId": question_id,
                "status": status,
                "error": str(e),
                "timestamp": start_time
            })

            self.file_stats[file_path]["fail"] += 1

    def _extract_status(self, msg):
        match = re.search(r"Status:\s*(\d{3})", msg)
        return match.group(1) if match else "ERROR"

    async def close(self):
        await self.client.close()

    def save_report(self, run_id):

        base = os.path.join(REPORT_DIR, run_id, f"worker_{self.worker_id}")
        os.makedirs(base, exist_ok=True)

        report = {
            "worker_id": self.worker_id,
            "summary": {
                "success": len(self.results["SUCCESS"]),
                "failed": sum(len(v) for k, v in self.results.items() if k != "SUCCESS")
            },
            "file_stats": dict(self.file_stats),
            "results": dict(self.results)
        }

        with open(os.path.join(base, "summary.json"), "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)

        Logger.success(f"Worker {self.worker_id} report saved")

def split_files(files, workers):
    chunks = [[] for _ in range(workers)]
    for i, f in enumerate(files):
        chunks[i % workers].append(f)
    return chunks


async def worker_runner(worker_id, files, rate_limiter, run_id):

    Logger.info(f"Worker {worker_id} started with {len(files)} files")

    worker = ApiWorker(worker_id, rate_limiter)
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
    worker.save_report(run_id)

    Logger.success(f"Worker {worker_id} completed")

def run_pipeline():

    run_id = datetime.now().strftime("run_%Y_%m_%d_%H_%M_%S")

    files = discover_files()

    if not files:
        Logger.error("No files found")
        return

    Logger.info(f"Total files: {len(files)}")
    Logger.info(f"Workers: {WORKERS}")
    Logger.info(f"Global Rate Limit: {GLOBAL_RATE_LIMIT_SECONDS}s per request")

    rate_limiter = GlobalRateLimiter(GLOBAL_RATE_LIMIT_SECONDS)

    file_chunks = split_files(files, WORKERS)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    tasks = [
        worker_runner(i, file_chunks[i], rate_limiter, run_id)
        for i in range(WORKERS)
    ]

    loop.run_until_complete(asyncio.gather(*tasks))

    Logger.success("PIPELINE COMPLETE")
if __name__ == "__main__":
    run_pipeline()