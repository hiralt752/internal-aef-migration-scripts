import os
import re
import json
import asyncio
import time
from datetime import datetime

from base_api_client import BaseApiClient


CREATE_ENDPOINT = (
    "https://ccl-rc-az.nprd.alefed.com/question-bank-service/api/v1/questions"
)

PUT_DRAFT_ENDPOINT = (
    "https://ccl-rc-az.nprd.alefed.com/question-bank-service/api/v1/questions/{questionId}:putDraft"
)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BASE_DIR)

TRANSFORM_DIR = os.path.join(PROJECT_ROOT, "transformation_engine")
INPUT_DIRS = [
    # os.path.join(TRANSFORM_DIR, "validation_error_fix_DND"),
    # os.path.join(TRANSFORM_DIR, "transformation_output_not_in_raw_data"),
    os.path.join(TRANSFORM_DIR, "test")
]
MAPPING_FILE = os.path.join(
    PROJECT_ROOT,
    "migration_id_mapping",
    "question_id_mapping.json"
)
REPORT_DIR = os.path.join(BASE_DIR, "api_reports_01")

CONCURRENCY = 10
QUEUE_MAXSIZE = 2000
MAX_CHUNK_SIZE_BYTES = 5 * 1024 * 1024

STATUS_RE = re.compile(r"Status:\s*(\d{3})")
PART_RE = re.compile(r"^(\d+)_part\d+\.json$")

def load_question_mapping():
    mapping = {}

    if not os.path.exists(MAPPING_FILE):
        Logger.error(f"Mapping file not found: {MAPPING_FILE}")
        return mapping

    try:
        with open(MAPPING_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        for row in data:
            old_id = row.get("old_id")
            new_id = row.get("new_id")

            if old_id:
                mapping[old_id] = new_id

        Logger.info(
            f"Loaded {len(mapping):,} question ID mappings"
        )

    except Exception as e:
        Logger.error(f"Failed loading mapping file: {e}")

    return mapping

def resolve_endpoint(old_question_id, question_mapping):
    """
    Returns:
        endpoint
        operation_type
        mapped_question_id
    """

    new_id = question_mapping.get(old_question_id)

    if new_id:
        return (
            PUT_DRAFT_ENDPOINT.format(questionId=new_id),
            "putDraft",
            new_id
        )

    return (
        CREATE_ENDPOINT,
        "create",
        None
    )

def parse_status_from_error(err_text):
    if not err_text:
        return None
    m = STATUS_RE.search(str(err_text))
    return int(m.group(1)) if m else None


def is_settled(code):
    """A finished outcome that must NOT be re-run."""
    if code is None:
        return False
    if 200 <= code < 300:      # created (200/201)
        return True
    if code in (409, 400):     # already-exists / bad-request
        return True
    return False


def classify(status_code):
    if status_code is None:
        return "failed"
    if 200 <= status_code < 300:
        return "created"
    if status_code == 409:
        return "exists"
    return "failed"


class Logger:
    @staticmethod
    def info(msg): print(f"[INFO] {msg}")
    @staticmethod
    def success(msg): print(f"[SUCCESS] {msg}")
    @staticmethod
    def error(msg): print(f"[ERROR] {msg}")


def format_log_fields(**fields):
    return " | ".join(
        f"{key}={value}" for key, value in fields.items() if value is not None
    )


def get_qid(payload):
    return (payload.get("metadata", {}).get("general", {}).get("externalId")
            or payload.get("question_id"))


def discover_files():
    files = []
    for d in INPUT_DIRS:
        if not os.path.isdir(d):
            Logger.error(f"Input folder missing (skipped): {d}")
            continue
        for root, _, filenames in os.walk(d):
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


def list_part_files():
    """Return {status_code: [file paths]} for top-level NNN_part*.json files."""
    result = {}
    if not os.path.isdir(REPORT_DIR):
        return result
    for name in os.listdir(REPORT_DIR):
        m = PART_RE.match(name)
        if not m:
            continue
        path = os.path.join(REPORT_DIR, name)
        if os.path.isfile(path):
            result.setdefault(int(m.group(1)), []).append(path)
    return result


def read_records(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else [data]
    except Exception:
        return []


def atomic_write_records(path, records):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False)
    os.replace(tmp, path)


def build_settled_and_baseline():
    """Scan part files. Return (settled_ids, success_base, failed_base)."""
    settled_ids = set()
    success_ids = set()
    failed_ids = set()
    parts = list_part_files()
    for code, paths in parts.items():
        if not is_settled(code):
            continue
        for p in paths:
            for rec in read_records(p):
                if isinstance(rec, dict):
                    qid = rec.get("question_id")
                    if not qid:
                        continue
                    settled_ids.add(qid)
                    if code == 400:
                        failed_ids.add(qid)
                    else:                 # 2xx or 409
                        success_ids.add(qid)
    return settled_ids, len(success_ids), len(failed_ids)


def clean_nonsettled_files(retry_ids):
    """Remove to-be-retried ids from non-settled part files (401/500/...),
    so their re-decided outcome doesn't duplicate the stale entry."""
    removed = 0
    parts = list_part_files()
    for code, paths in parts.items():
        if is_settled(code):
            continue
        for p in paths:
            recs = read_records(p)
            kept = [r for r in recs
                    if not (isinstance(r, dict) and r.get("question_id") in retry_ids)]
            if len(kept) != len(recs):
                removed += len(recs) - len(kept)
                atomic_write_records(p, kept)
    return removed


class StatusWriter:
    """Buffer per status; write each chunk ONCE at 5 MB. Continues the latest
    existing part file for each status. Synchronous => atomic on the loop."""
    def __init__(self, report_dir, max_chunk):
        self.dir = report_dir
        self.max_chunk = max_chunk
        self.part = {}
        self.buf = {}
        self.size = {}
        os.makedirs(report_dir, exist_ok=True)

    def _init_status(self, status):
        part = 1
        while True:
            cand = os.path.join(self.dir, f"{status}_part{part}.json")
            if not os.path.exists(cand):
                self.part[status] = part; self.buf[status] = []; self.size[status] = 0
                return
            if os.path.getsize(cand) < self.max_chunk:
                try:
                    with open(cand, "r", encoding="utf-8") as f:
                        existing = json.load(f)
                    if not isinstance(existing, list):
                        existing = [existing]
                except Exception:
                    existing = []
                strs = [json.dumps(r, ensure_ascii=False) for r in existing]
                self.part[status] = part; self.buf[status] = strs
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
        path = os.path.join(self.dir, f"{status}_part{self.part[status]}.json")
        strs = self.buf[status]
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write("[\n" + ",\n".join(strs) + "\n]" if strs else "[]")
        os.replace(tmp, path)
        if advance:
            self.part[status] += 1; self.buf[status] = []; self.size[status] = 0

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
        if outcome in ("created", "exists"):
            self.success += 1
        else:
            self.failed += 1
        return self.success, self.failed, self.success + self.failed


async def handle_post(client, payload, writer, counters,question_mapping):
    ''' 
        operation = create ( it will create a new record in Server B no need to pass question id )
        operation = putDraft ( it will update an existing record in Server B and need to pass question id )
    '''
    qid = get_qid(payload)
    qtype = payload.get("type")
    endpoint, operation, mapped_id = resolve_endpoint(
        qid,
        question_mapping
    )
    api_name = "putDraft" if operation == "putDraft" else "post"
    ts = datetime.now().isoformat()
    try:
        Logger.info(
            "API request started | "
            + format_log_fields(
                api=api_name,
                operation=operation,
                question_id=qid,
                mapped_question_id=mapped_id,
                question_type=qtype
            )
        )
        response = await client.post(endpoint, payload=payload)
        status = getattr(response, "status_code", 200)
        try:
            body = response.json() if hasattr(response, "json") else response
        except Exception:
            body = str(response)
        outcome = classify(status)
        writer.add(status, {"question_id": qid, "question_type": qtype,"operation": operation,"mapped_question_id": mapped_id,
                            "response": body, "timestamp": ts})
    except Exception as e:
        err = str(e)
        status = parse_status_from_error(err)
        outcome = classify(status)
        writer.add(status if status is not None else 500,
                   {"question_id": qid, "question_type": qtype,
                    "response": err, "timestamp": ts})
    s, fl, tot = counters.record(outcome)
    log_message = (
        "API request completed | "
        + format_log_fields(
            api=api_name,
            operation=operation,
            question_id=qid,
            mapped_question_id=mapped_id,
            status=status if status is not None else "ERR",
            outcome=outcome,
            total=tot,
            success=s,
            failed=fl
        )
    )
    if outcome in ("created", "exists"):
        Logger.success(log_message)
    else:
        Logger.error(log_message)


async def producer(queue, files, settled_ids):
    for fp in files:
        for payload in await asyncio.to_thread(load_payloads, fp):
            if get_qid(payload) in settled_ids:
                continue
            await queue.put(payload)
    for _ in range(CONCURRENCY):
        await queue.put(None)


async def consumer(queue, writer, counters,question_mapping):
    client = BaseApiClient()
    try:
        while True:
            payload = await queue.get()
            if payload is None:
                queue.task_done(); break
            await handle_post(client, payload, writer, counters,question_mapping)
            queue.task_done()
    finally:
        await client.close()


async def run_async(files, settled_ids, writer, counters,question_mapping):
    queue = asyncio.Queue(maxsize=QUEUE_MAXSIZE)
    prod = asyncio.create_task(producer(queue, files, settled_ids))
    cons = [asyncio.create_task(consumer(queue, writer, counters,question_mapping)) for _ in range(CONCURRENCY)]
    await prod
    await asyncio.gather(*cons)


def run_pipeline():
    start = time.time()
    question_mapping = load_question_mapping()
    files = discover_files()
    if not files:
        Logger.error("No input files found in either folder.")
        return
    Logger.info(f"Input files: {len(files)} (across {len(INPUT_DIRS)} folders)")
    Logger.info(f"Concurrency: {CONCURRENCY}")

    # 1) what's already settled (200/201/409/400) + baseline counts
    settled_ids, success_base, failed_base = build_settled_and_baseline()
    Logger.info(f"Settled ids (skip): {len(settled_ids):,} | "
                f"baseline success={success_base:,} failed={failed_base:,}")

    # 2) which input ids will be retried (not settled) -> for stale cleanup
    retry_ids = set()
    for fp in files:
        for payload in load_payloads(fp):
            qid = get_qid(payload)
            if qid and qid not in settled_ids:
                retry_ids.add(qid)
    Logger.info(f"To retry: {len(retry_ids):,}")

    # 3) pull those ids out of the stale non-settled files (401/500/...)
    removed = clean_nonsettled_files(retry_ids)
    Logger.info(f"Removed {removed:,} stale records from non-settled files")

    # 4) run, appending into the latest part file per status
    writer = StatusWriter(REPORT_DIR, MAX_CHUNK_SIZE_BYTES)
    counters = Counters(success_base, failed_base)
    try:
        asyncio.run(run_async(files, settled_ids, writer, counters,question_mapping))
    finally:
        writer.flush_all()

    dur = time.time() - start
    print("\n================ DONE ================")
    print(f"New calls this run : {counters.run_calls:,}")
    print(f"Success (total)    : {counters.success:,}")
    print(f"Failed  (total)    : {counters.failed:,}")
    print(f"Grand total        : {counters.success + counters.failed:,}")
    print(f"Time               : {dur:.2f}s"
          + (f"  ({counters.run_calls/dur:.1f} req/s)" if dur > 0 else ""))
    print("======================================")


if __name__ == "__main__":
    run_pipeline()
