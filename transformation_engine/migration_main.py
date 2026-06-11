import os
import json
import asyncio
import time
import random
import re
from datetime import datetime
from collections import defaultdict

from base_api_client import BaseApiClient


# =========================
# CONFIG
# =========================

ENDPOINT = "https://ccl-rc-az.nprd.alefed.com/question-bank-service/api/v1/questions"

INPUT_DIR = r"D:\Alef_Final_Chapter\internal-aef-migration-scripts\transformation_engine\transformation_output"

REPORT_DIR = "api_reports"

GLOBAL_RATE_LIMIT_SECONDS = 4   # 🔥 YOUR REQUIREMENT


# =========================
# LOGGER
# =========================

class Logger:
    @staticmethod
    def info(msg): print(f"[INFO] {msg}")
    @staticmethod
    def success(msg): print(f"[SUCCESS] {msg}")
    @staticmethod
    def error(msg): print(f"[ERROR] {msg}")


# =========================
# GLOBAL RATE LIMITER (OPTION 1)
# =========================

class GlobalRateLimiter:

    def __init__(self, delay_seconds: float):
        self.delay = delay_seconds
        self.lock = asyncio.Lock()
        self.last_call_time = 0

    async def wait(self):
        async with self.lock:

            now = time.time()
            wait_time = self.delay - (now - self.last_call_time)

            if wait_time > 0:
                await asyncio.sleep(wait_time)

            self.last_call_time = time.time()


# =========================
# FILE DISCOVERY
# =========================

def discover_files():
    files = []

    for root, _, filenames in os.walk(INPUT_DIR):
        for f in filenames:
            if f.endswith(".json"):
                files.append(os.path.join(root, f))

    return files


# =========================
# LOAD PAYLOADS
# =========================

def load_payloads(file_path):
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        return data if isinstance(data, list) else [data]

    except Exception as e:
        Logger.error(f"Failed loading {file_path} | {e}")
        return []


# =========================
# API WORKER
# =========================

class ApiWorker:

    def __init__(self, worker_id, rate_limiter):
        self.worker_id = worker_id
        self.rate_limiter = rate_limiter
        self.client = BaseApiClient()

        self.results = defaultdict(list)
        self.file_stats = defaultdict(lambda: {"success": 0, "fail": 0})

    # -------------------------
    async def process_file(self, file_path, payloads):

        tasks = [
            self._post_payload(file_path, payload)
            for payload in payloads
        ]

        await asyncio.gather(*tasks)

    # -------------------------
    async def _post_payload(self, file_path, payload):

        question_id = payload.get("metadata", {}).get("general", {}).get("externalId")

        try:

            # 🔥 GLOBAL RATE LIMIT APPLIED HERE (CRITICAL)
            await self.rate_limiter.wait()

            response = await self.client.post(ENDPOINT, payload=payload)

            self.results["SUCCESS"].append({
                "file": file_path,
                "questionId": question_id,
                "status": "SUCCESS",
                "timestamp": datetime.now().isoformat()
            })

            self.file_stats[file_path]["success"] += 1

        except Exception as e:

            status = self._extract_status(str(e))

            self.results[status].append({
                "file": file_path,
                "questionId": question_id,
                "status": status,
                "error": str(e),
                "timestamp": datetime.now().isoformat()
            })

            self.file_stats[file_path]["fail"] += 1

    # -------------------------
    def _extract_status(self, msg):
        match = re.search(r"Status:\s*(\d{3})", msg)
        return match.group(1) if match else "ERROR"

    # -------------------------
    async def close(self):
        await self.client.close()

    # -------------------------
    def save_report(self, run_id):

        base = os.path.join(REPORT_DIR, run_id, f"worker_{self.worker_id}")
        os.makedirs(base, exist_ok=True)

        report = {
            "worker_id": self.worker_id,
            "summary": {
                "success": len(self.results["SUCCESS"]),
                "failed": sum(len(v) for k, v in self.results.items() if k != "SUCCESS")
            },
            "file_stats": self.file_stats,
            "results": self.results
        }

        with open(os.path.join(base, "summary.json"), "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)

        Logger.success(f"Worker {self.worker_id} report saved")


# =========================
# WORK DISTRIBUTION
# =========================

def split_files(files, workers):
    chunks = [[] for _ in range(workers)]

    for i, f in enumerate(files):
        chunks[i % workers].append(f)

    return chunks


# =========================
# WORKER RUNNER
# =========================

async def run_worker(worker_id, files, rate_limiter, run_id):

    Logger.info(f"Worker {worker_id} started with {len(files)} files")

    worker = ApiWorker(worker_id, rate_limiter)

    try:

        for file_path in files:

            Logger.info(f"Worker {worker_id} processing {file_path}")

            payloads = load_payloads(file_path)

            if not payloads:
                continue

            await worker.process_file(file_path, payloads)

    finally:
        await worker.close()
        worker.save_report(run_id)

    Logger.success(f"Worker {worker_id} completed")


# =========================
# MAIN PIPELINE
# =========================

def run_pipeline():

    run_id = datetime.now().strftime("run_%Y_%m_%d_%H_%M_%S")

    files = discover_files()

    if not files:
        Logger.error("No files found")
        return

    workers = min(8, os.cpu_count() or 4)

    Logger.info(f"Total files: {len(files)}")
    Logger.info(f"Workers: {workers}")
    Logger.info(f"GLOBAL API GAP: {GLOBAL_RATE_LIMIT_SECONDS}s")

    # 🔥 GLOBAL RATE LIMITER (SHARED ACROSS ALL WORKERS)
    rate_limiter = GlobalRateLimiter(GLOBAL_RATE_LIMIT_SECONDS)

    file_chunks = split_files(files, workers)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    tasks = [
        run_worker(i, file_chunks[i], rate_limiter, run_id)
        for i in range(workers)
    ]

    loop.run_until_complete(asyncio.gather(*tasks))

    Logger.success("MIGRATION COMPLETE")


# =========================
# ENTRY POINT
# =========================

if __name__ == "__main__":
    run_pipeline()