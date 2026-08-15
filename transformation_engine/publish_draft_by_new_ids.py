import argparse
import asyncio
import json
import logging
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import httpx

# Ensure transformation_engine directory is on sys.path for BaseApiClient
TRANSFORM_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = TRANSFORM_DIR.parent
if str(TRANSFORM_DIR) not in sys.path:
    sys.path.insert(0, str(TRANSFORM_DIR))

from base_api_client import BaseApiClient

PUBLISH_ENDPOINT = (
    "https://shared.alefed.com/question-bank-service/api/v1/questions/{questionId}:publish"
)

DEFAULT_INPUT_FILE = PROJECT_ROOT / "to_publish_new_ids.json"
DEFAULT_REPORT_DIR = TRANSFORM_DIR / "to_publish_new_ids_api_report"
LOG_DIR = TRANSFORM_DIR / "logs"

CONCURRENCY = 10
REQUESTS_PER_SECOND = 10
QUEUE_MAXSIZE = 2000
MAX_CHUNK_SIZE_BYTES = 5 * 1024 * 1024
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}

STATUS_RE = re.compile(r"Status:\s*(\d{3})")
PART_RE = re.compile(r"^(\d+)_part\d+\.json$")
UUID_RE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")


def _build_logger() -> logging.Logger:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = LOG_DIR / f"publish_draft_by_new_ids_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

    logger = logging.getLogger("publish_draft_by_new_ids")
    logger.setLevel(logging.INFO)
    logger.propagate = False

    if not logger.handlers:
        fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")

        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(fmt)
        logger.addHandler(console_handler)

        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(fmt)
        logger.addHandler(file_handler)

    return logger


_logger = _build_logger()


class Logger:
    @staticmethod
    def info(msg):
        _logger.info(msg)

    @staticmethod
    def success(msg):
        _logger.info(f"SUCCESS | {msg}")

    @staticmethod
    def error(msg):
        _logger.error(msg)


def format_log_fields(**fields):
    return " | ".join(
        f"{key}={value}" for key, value in fields.items() if value is not None
    )


class AsyncRateLimiter:
    """Serialize request starts to stay under the external API rate cap."""

    def __init__(self, requests_per_second):
        self.min_interval = 1.0 / requests_per_second
        self._lock = asyncio.Lock()
        self._next_allowed = 0.0

    async def acquire(self):
        async with self._lock:
            loop = asyncio.get_running_loop()
            now = loop.time()
            wait_time = self._next_allowed - now
            if wait_time > 0:
                await asyncio.sleep(wait_time)
                now = loop.time()
            self._next_allowed = now + self.min_interval


def parse_status_from_error(err_text):
    if not err_text:
        return None
    m = STATUS_RE.search(str(err_text))
    return int(m.group(1)) if m else None


def is_settled(code):
    """A finished publish outcome that must NOT be re-run."""
    if code is None:
        return False
    if 200 <= code < 300:
        return True
    if code in (400, 409):
        return True
    return False


def classify(status_code):
    if status_code is None:
        return "failed"
    if 200 <= status_code < 300:
        return "published"
    if status_code == 409:
        return "already_published_or_conflict"
    return "failed"


def load_new_ids_from_file(input_file: Path) -> list[dict[str, str]]:
    if not input_file.exists():
        Logger.error(f"Input file not found: {input_file}")
        return []

    with input_file.open("r", encoding="utf-8") as f:
        data = json.load(f)

    records = []
    items = data if isinstance(data, list) else [data]

    for item in items:
        if isinstance(item, str):
            match = UUID_RE.search(item)
            if match:
                records.append({"new_id": match.group(0).lower(), "old_id": ""})
        elif isinstance(item, dict):
            new_id = str(item.get("new_id") or item.get("question_id") or item.get("questionId") or "").strip().lower()
            old_id = str(item.get("old_id") or "").strip().lower()
            if new_id:
                records.append({"new_id": new_id, "old_id": old_id})

    return records


def list_part_files(report_dir: Path) -> dict[int, list[Path]]:
    result = {}
    if not report_dir.exists():
        return result
    for child in report_dir.iterdir():
        m = PART_RE.match(child.name)
        if m and child.is_file():
            result.setdefault(int(m.group(1)), []).append(child)
    return result


def read_records(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else [data]
    except Exception:
        return []


def atomic_write_records(path: Path, records):
    tmp = str(path) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False)
    os.replace(tmp, path)


def build_settled_and_baseline(report_dir: Path):
    settled_ids = set()
    success_ids = set()
    failed_ids = set()
    parts = list_part_files(report_dir)
    for code, paths in parts.items():
        if not is_settled(code):
            continue
        for p in paths:
            for rec in read_records(p):
                if isinstance(rec, dict):
                    qid = rec.get("mapped_question_id") or rec.get("new_id")
                    if not qid:
                        continue
                    settled_ids.add(qid.lower())
                    if code == 400:
                        failed_ids.add(qid.lower())
                    else:
                        success_ids.add(qid.lower())
    return settled_ids, len(success_ids), len(failed_ids)


def clean_nonsettled_files(report_dir: Path, retry_ids: set[str]):
    removed = 0
    parts = list_part_files(report_dir)
    for code, paths in parts.items():
        if is_settled(code):
            continue
        for p in paths:
            recs = read_records(p)
            kept = [
                r for r in recs
                if not (isinstance(r, dict) and (r.get("mapped_question_id") or r.get("new_id")) in retry_ids)
            ]
            if len(kept) != len(recs):
                removed += len(recs) - len(kept)
                atomic_write_records(p, kept)
    return removed


class StatusWriter:
    def __init__(self, report_dir: Path, max_chunk: int):
        self.dir = report_dir
        self.max_chunk = max_chunk
        self.part = {}
        self.buf = {}
        self.size = {}
        self.dir.mkdir(parents=True, exist_ok=True)

    def _init_status(self, status):
        part = 1
        while True:
            cand = self.dir / f"{status}_part{part}.json"
            if not cand.exists():
                self.part[status] = part
                self.buf[status] = []
                self.size[status] = 0
                return
            if cand.stat().st_size < self.max_chunk:
                try:
                    with cand.open("r", encoding="utf-8") as f:
                        existing = json.load(f)
                    if not isinstance(existing, list):
                        existing = [existing]
                except Exception:
                    existing = []
                strs = [json.dumps(r, ensure_ascii=False) for r in existing]
                self.part[status] = part
                self.buf[status] = strs
                self.size[status] = sum(len(s) for s in strs) + 2 * len(strs)
                return
            part += 1

    def add(self, status, record):
        if status not in self.part:
            self._init_status(status)
        s = json.dumps(record, ensure_ascii=False)
        self.buf[status].append(s)
        self.size[status] += len(s) + 2
        if self.size[status] >= self.max_chunk:
            self._flush(status, advance=True)

    def _flush(self, status, advance):
        path = self.dir / f"{status}_part{self.part[status]}.json"
        strs = self.buf[status]
        tmp = str(path) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write("[\n" + ",\n".join(strs) + "\n]" if strs else "[]")
        os.replace(tmp, path)
        if advance:
            self.part[status] += 1
            self.buf[status] = []
            self.size[status] = 0

    def flush_all(self):
        for status in list(self.part.keys()):
            self._flush(status, advance=False)


class Counters:
    def __init__(self, success_base, failed_base):
        self.success = success_base
        self.failed = failed_base
        self.run_calls = 0

    def record(self, outcome):
        self.run_calls += 1
        if outcome in ("published", "already_published_or_conflict"):
            self.success += 1
        else:
            self.failed += 1
        return self.success, self.failed, self.success + self.failed


async def post_publish(client, endpoint, rate_limiter=None):
    for attempt in range(3):
        try:
            if rate_limiter is not None:
                await rate_limiter.acquire()
            response = await client.client.post(endpoint)
            response.raise_for_status()
            return response
        except (httpx.TimeoutException, httpx.RequestError) as e:
            if attempt < 2:
                Logger.info(f"Transport error, retrying (attempt {attempt + 1}/3) | {endpoint} | {e}")
                await asyncio.sleep(1 * (attempt + 1))
            else:
                raise Exception(f"Failed after retries: {endpoint} | Error: {e}")
        except httpx.HTTPStatusError as e:
            status = e.response.status_code
            if status in RETRYABLE_STATUS_CODES and attempt < 2:
                Logger.info(f"Status {status}, retrying (attempt {attempt + 1}/3) | {endpoint}")
                await asyncio.sleep(1 * (attempt + 1))
                continue
            raise Exception(
                f"HTTP error on POST {endpoint} | "
                f"Status: {status} | "
                f"Response: {e.response.text}"
            )


async def handle_publish(client, record, writer, counters, rate_limiter):
    new_id = record["new_id"]
    old_id = record.get("old_id", "")
    ts = datetime.now().isoformat()
    endpoint = PUBLISH_ENDPOINT.format(questionId=new_id)

    try:
        Logger.info(
            "API request started | "
            + format_log_fields(
                api="publishDraft",
                operation="publishDraft",
                new_id=new_id,
                old_id=old_id,
            )
        )
        response = await post_publish(client, endpoint, rate_limiter=rate_limiter)
        status = getattr(response, "status_code", 200)
        try:
            body = response.json() if response.content else None
        except Exception:
            body = response.text
        outcome = classify(status)
        writer.add(
            status,
            {
                "question_id": old_id,
                "mapped_question_id": new_id,
                "operation": "publishDraft",
                "response": body,
                "timestamp": ts,
            },
        )
    except Exception as e:
        err = str(e)
        status = parse_status_from_error(err)
        outcome = classify(status)
        writer.add(
            status if status is not None else 500,
            {
                "question_id": old_id,
                "mapped_question_id": new_id,
                "operation": "publishDraft",
                "response": err,
                "timestamp": ts,
            },
        )

    s, fl, tot = counters.record(outcome)
    log_message = (
        "API request completed | "
        + format_log_fields(
            api="publishDraft",
            operation="publishDraft",
            mapped_question_id=new_id,
            status=status if status is not None else "ERR",
            outcome=outcome,
            total=tot,
            success=s,
            failed=fl,
        )
    )
    if outcome in ("published", "already_published_or_conflict"):
        Logger.success(log_message)
    else:
        Logger.error(log_message)


async def producer(queue, records, settled_ids):
    for rec in records:
        if rec["new_id"] in settled_ids:
            continue
        await queue.put(rec)
    for _ in range(CONCURRENCY):
        await queue.put(None)


async def consumer(queue, writer, counters, rate_limiter):
    client = BaseApiClient()
    try:
        while True:
            rec = await queue.get()
            if rec is None:
                queue.task_done()
                break
            await handle_publish(client, rec, writer, counters, rate_limiter)
            queue.task_done()
    finally:
        await client.close()


async def run_async(records, settled_ids, writer, counters):
    queue = asyncio.Queue(maxsize=QUEUE_MAXSIZE)
    rate_limiter = AsyncRateLimiter(REQUESTS_PER_SECOND)
    prod = asyncio.create_task(producer(queue, records, settled_ids))
    cons = [
        asyncio.create_task(consumer(queue, writer, counters, rate_limiter))
        for _ in range(CONCURRENCY)
    ]
    await prod
    await asyncio.gather(*cons)


def main():
    parser = argparse.ArgumentParser(
        description="Publish DRAFT questions to PUBLISHED status via question bank service API."
    )
    parser.add_argument("--input-file", type=Path, default=DEFAULT_INPUT_FILE, help="JSON file containing new_ids.")
    parser.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT_DIR, help="Directory to save API execution reports.")
    args = parser.parse_args()

    start = time.time()
    records = load_new_ids_from_file(args.input_file)
    if not records:
        Logger.error(f"No records found in {args.input_file}")
        return

    Logger.info(f"Loaded {len(records):,} target question IDs from {args.input_file}")
    Logger.info(f"Concurrency: {CONCURRENCY}")
    Logger.info(f"Rate limit: {REQUESTS_PER_SECOND} req/s")
    Logger.info(f"Publish endpoint: {PUBLISH_ENDPOINT}")

    settled_ids, success_base, failed_base = build_settled_and_baseline(args.report_dir)
    Logger.info(
        f"Settled question IDs (skip): {len(settled_ids):,} | "
        f"baseline success={success_base:,} failed={failed_base:,}"
    )

    retry_records = [r for r in records if r["new_id"] not in settled_ids]
    retry_ids = {r["new_id"] for r in retry_records}
    Logger.info(f"To publish/retry: {len(retry_records):,}")

    removed = clean_nonsettled_files(args.report_dir, retry_ids)
    Logger.info(f"Removed {removed:,} stale records from non-settled files")

    writer = StatusWriter(args.report_dir, MAX_CHUNK_SIZE_BYTES)
    counters = Counters(success_base, failed_base)

    try:
        asyncio.run(run_async(retry_records, settled_ids, writer, counters))
    finally:
        writer.flush_all()

    dur = time.time() - start
    Logger.info("================ DONE ================")
    Logger.info(f"New calls this run : {counters.run_calls:,}")
    Logger.info(f"Success (total)    : {counters.success:,}")
    Logger.info(f"Failed  (total)    : {counters.failed:,}")
    Logger.info(f"Grand total        : {counters.success + counters.failed:,}")
    Logger.info(f"Time               : {dur:.2f}s" + (f"  ({counters.run_calls/dur:.1f} req/s)" if dur > 0 else ""))
    Logger.info("======================================")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        Logger.error("Interrupted by user")
        sys.exit(130)
    except Exception:
        _logger.exception("Fatal error while running publish_draft_by_new_ids")
        sys.exit(1)
