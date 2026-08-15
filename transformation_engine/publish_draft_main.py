import os
import re
import json
import asyncio
import time
from datetime import datetime

import httpx

from base_api_client import BaseApiClient


PUBLISH_DRAFT_ENDPOINT = (
    "https://shared.alefed.com/question-bank-service/api/v1/questions/{questionId}:publish"
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BASE_DIR)

TRANSFORM_DIR = os.path.join(PROJECT_ROOT, "transformation_engine")
INPUT_DIRS = [
    os.path.join(TRANSFORM_DIR, "Priority POOL DATA 14 Aug_transformed_migration_ready")
]
MAPPING_FILE = os.path.join(
    PROJECT_ROOT,
    "migration_id_mapping",
    "question_id_mapping.json"
)

# The putDraft/migration report for this same batch (produced by
# migration_main.py): NNN_part*.json files, one folder of files per status
# code, each record carrying "mapped_question_id" (the NEW id resolved via
# question_id_mapping.json). This report - not a published-list CSV - is
# now the sole source of publish eligibility: a question is eligible only
# if its migration call settled with status 200, 201, or 409 here. See
# load_migration_report_eligibility().
DRAFT_REPORT_DIR = os.path.join(TRANSFORM_DIR, "Priority POOL DATA 14 Aug_transformed_migration_ready_report")

# Migration-report statuses that make a question eligible for publishing.
# 200/201 = draft created/updated; 409 = draft already exists - still
# eligible per the requirement. This is the migration report's own status
# code and is unrelated to a 409 the Publish API itself might return later.
ELIGIBLE_MIGRATION_STATUSES = (200, 201, 409)

REPORT_DIR = os.path.join(TRANSFORM_DIR, "Priority POOL DATA 14 Aug_transformed_migration_ready_report_publish_report")

# When set, compute and print the eligibility summary (Step 12) without
# writing any file or calling the Publish API.
PUBLISH_DRY_RUN = (
    os.environ.get("PUBLISH_DRY_RUN", "false").strip().lower()
    in {"1", "true", "yes", "on"}
)

CONCURRENCY = 10
REQUESTS_PER_SECOND = 10
QUEUE_MAXSIZE = 2000
MAX_CHUNK_SIZE_BYTES = 5 * 1024 * 1024

STATUS_RE = re.compile(r"Status:\s*(\d{3})")
PART_RE = re.compile(r"^(\d+)_part\d+\.json$")


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

            if old_id and new_id:
                mapping[old_id] = new_id

        Logger.info(f"Loaded {len(mapping):,} question ID mappings")

    except Exception as e:
        Logger.error(f"Failed loading mapping file: {e}")

    return mapping


def load_migration_report_eligibility(report_dir):
    """Sole eligibility source for publishing: an id is eligible only if its
    migration (create/putDraft) call, recorded in this report folder
    (NNN_part*.json, produced by migration_main.py), settled with status
    200, 201, or 409. "mapped_question_id" in each record is already the
    NEW id (see migration_main.py's resolve_endpoint/handle_post), so no
    further mapping step is needed for the ids collected here.

    Returns (eligible_ids, ids_by_status) where ids_by_status is
    {200: set(...), 201: set(...), 409: set(...)} - kept separate so the
    caller can report per-status counts and detect ids settled under more
    than one status (e.g. reprocessed between runs).
    """
    ids_by_status = {status: set() for status in ELIGIBLE_MIGRATION_STATUSES}

    if not os.path.isdir(report_dir):
        Logger.error(f"Migration report folder missing: {report_dir}")
        return set(), ids_by_status

    for name in os.listdir(report_dir):
        m = PART_RE.match(name)
        if not m:
            continue

        status = int(m.group(1))
        if status not in ELIGIBLE_MIGRATION_STATUSES:
            continue

        path = os.path.join(report_dir, name)
        if not os.path.isfile(path):
            continue

        for rec in read_records(path):
            if not isinstance(rec, dict):
                continue

            mapped_id = rec.get("mapped_question_id")
            if not mapped_id:
                continue

            ids_by_status[status].add(mapped_id)

    eligible_ids = set()
    for ids in ids_by_status.values():
        eligible_ids |= ids

    duplicates = set()
    statuses = list(ids_by_status.keys())
    for i, s1 in enumerate(statuses):
        for s2 in statuses[i + 1:]:
            duplicates |= ids_by_status[s1] & ids_by_status[s2]

    Logger.info(
        "Migration report eligibility | "
        + " ".join(f"{status}={len(ids_by_status[status]):,}" for status in ELIGIBLE_MIGRATION_STATUSES)
        + f" | unique_eligible={len(eligible_ids):,} | duplicates_across_statuses={len(duplicates):,}"
    )

    return eligible_ids, ids_by_status


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


def get_qid(payload):
    return (payload.get("metadata", {}).get("general", {}).get("externalId")
            or payload.get("question_id")
            or payload.get("questionId")
            or payload.get("externalId")
            or payload.get("id"))


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


class EligibilityStats:
    """Accumulates the pre-flight eligibility pass (Step 12/14 summary)
    across all input files."""
    def __init__(self):
        self.total_records = 0
        self.missing_mapping = 0
        self.not_eligible = 0
        self.already_published = 0
        self.eligible = 0


def mark_published_and_collect(file_path, question_mapping, eligible_new_ids, id_status=None, stats=None, dry_run=False):
    """PART 2 (local half): load one input file: for every record whose
    mapped new id is eligible per the migration report (200/201/409), flip
    metadata.lifecycle.status to PUBLISHED and write the file back;
    everything else in the file is left untouched. Returns just the
    now-PUBLISHED records, so the caller can queue them for the actual
    publish API call - which must only happen after this local status
    flip, per the required order.

    dry_run=True performs the same eligibility checks, logging, and stats
    collection but never mutates or writes the file - used for the Step 12
    validation pass, which must not touch data before any Publish API call.
    """
    records = load_payloads(file_path)
    if not records:
        return []

    eligible = []
    changed = False

    for rec in records:
        if not isinstance(rec, dict):
            continue

        if stats is not None:
            stats.total_records += 1

        old_qid = get_qid(rec)
        mapped_id = question_mapping.get(old_qid)

        if not mapped_id:
            Logger.info(f"[SKIPPED] Old ID: {old_qid} -> Missing ID mapping")
            if stats is not None:
                stats.missing_mapping += 1
            continue

        if mapped_id not in eligible_new_ids:
            Logger.info(f"[SKIPPED] Old ID: {old_qid} -> Not found in 200/201/409")
            if stats is not None:
                stats.not_eligible += 1
            continue

        migration_status = (id_status or {}).get(mapped_id)
        Logger.info(
            f"[ELIGIBLE] Old ID: {old_qid} -> New ID: {mapped_id} -> "
            f"Migration Status: {migration_status}"
        )
        if stats is not None:
            stats.eligible += 1

        metadata = rec.get("metadata") or {}
        lifecycle = metadata.get("lifecycle") or {}
        already_published = lifecycle.get("status") == "PUBLISHED"
        if stats is not None and already_published:
            stats.already_published += 1

        if dry_run:
            eligible.append(rec)
            continue

        metadata = rec.setdefault("metadata", {})
        lifecycle = metadata.setdefault("lifecycle", {})
        if not already_published:
            lifecycle["status"] = "PUBLISHED"
            changed = True

        eligible.append(rec)

    if changed and not dry_run:
        atomic_write_records(file_path, records)

    return eligible


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
    """Scan part files. Return (settled_new_ids, success_base, failed_base)."""
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
                    qid = rec.get("mapped_question_id")
                    if not qid:
                        continue
                    settled_ids.add(qid)
                    if code == 400:
                        failed_ids.add(qid)
                    else:
                        success_ids.add(qid)
    return settled_ids, len(success_ids), len(failed_ids)


def clean_nonsettled_files(retry_ids):
    """Remove to-be-retried ids from non-settled part files."""
    removed = 0
    parts = list_part_files()
    for code, paths in parts.items():
        if is_settled(code):
            continue
        for p in paths:
            recs = read_records(p)
            kept = [
                r for r in recs
                if not (isinstance(r, dict) and r.get("mapped_question_id") in retry_ids)
            ]
            if len(kept) != len(recs):
                removed += len(recs) - len(kept)
                atomic_write_records(p, kept)
    return removed


class StatusWriter:
    """Buffer per status; write each chunk once at 5 MB."""
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
        self.skipped_unmapped = 0

    def record(self, outcome):
        self.run_calls += 1
        if outcome in ("published", "already_published_or_conflict"):
            self.success += 1
        else:
            self.failed += 1
        return self.success, self.failed, self.success + self.failed

    def mark_skipped_unmapped(self):
        self.skipped_unmapped += 1


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
                await asyncio.sleep(1 * (attempt + 1))
            else:
                raise Exception(f"Failed after retries: {endpoint} | Error: {e}")

        except httpx.HTTPStatusError as e:
            raise Exception(
                f"HTTP error on POST {endpoint} | "
                f"Status: {e.response.status_code} | "
                f"Response: {e.response.text}"
            )


async def handle_publish(client, payload, writer, counters, question_mapping, rate_limiter):
    old_qid = get_qid(payload)
    qtype = payload.get("type") if isinstance(payload, dict) else None
    mapped_id = question_mapping.get(old_qid)
    ts = datetime.now().isoformat()

    if not mapped_id:
        counters.mark_skipped_unmapped()
        Logger.info(
            "API request skipped | "
            + format_log_fields(
                operation="publishDraft",
                question_id=old_qid,
                question_type=qtype,
                reason="missing mapped question id"
            )
        )
        return

    endpoint = PUBLISH_DRAFT_ENDPOINT.format(questionId=mapped_id)
    try:
        Logger.info(
            "API request started | "
            + format_log_fields(
                api="publishDraft",
                operation="publishDraft",
                question_id=old_qid,
                mapped_question_id=mapped_id,
                question_type=qtype
            )
        )
        response = await post_publish(
            client,
            endpoint,
            rate_limiter=rate_limiter
        )
        status = getattr(response, "status_code", 200)
        try:
            body = response.json() if response.content else None
        except Exception:
            body = response.text
        outcome = classify(status)
        writer.add(
            status,
            {
                "question_id": old_qid,
                "question_type": qtype,
                "operation": "publishDraft",
                "mapped_question_id": mapped_id,
                "response": body,
                "timestamp": ts
            }
        )
    except Exception as e:
        err = str(e)
        status = parse_status_from_error(err)
        outcome = classify(status)
        writer.add(
            status if status is not None else 500,
            {
                "question_id": old_qid,
                "question_type": qtype,
                "operation": "publishDraft",
                "mapped_question_id": mapped_id,
                "response": err,
                "timestamp": ts
            }
        )

    s, fl, tot = counters.record(outcome)
    log_message = (
        "API request completed | "
        + format_log_fields(
            api="publishDraft",
            operation="publishDraft",
            question_id=old_qid,
            mapped_question_id=mapped_id,
            status=status if status is not None else "ERR",
            outcome=outcome,
            total=tot,
            success=s,
            failed=fl
        )
    )
    if outcome in ("published", "already_published_or_conflict"):
        Logger.success(log_message)
    else:
        Logger.error(log_message)


async def producer(queue, payloads):
    for payload in payloads:
        await queue.put(payload)
    for _ in range(CONCURRENCY):
        await queue.put(None)


async def consumer(queue, writer, counters, question_mapping, rate_limiter):
    client = BaseApiClient()
    try:
        while True:
            payload = await queue.get()
            if payload is None:
                queue.task_done(); break
            await handle_publish(
                client,
                payload,
                writer,
                counters,
                question_mapping,
                rate_limiter
            )
            queue.task_done()
    finally:
        await client.close()


def collect_published_mapping(report_dir):
    """Scan this script's own report dir for every successful (200/201)
    publish outcome recorded so far - this run and all previous ones - and
    return {new_id: old_id} for everything actually PUBLISHED.
    """
    published = {}

    if not os.path.isdir(report_dir):
        return published

    for name in os.listdir(report_dir):
        m = PART_RE.match(name)
        if not m:
            continue

        status = int(m.group(1))
        if not (200 <= status < 300):
            continue

        path = os.path.join(report_dir, name)
        if not os.path.isfile(path):
            continue

        for rec in read_records(path):
            if not isinstance(rec, dict):
                continue

            mapped_id = rec.get("mapped_question_id")
            if not mapped_id:
                continue

            published[mapped_id] = rec.get("question_id")

    return published


async def run_async(payloads, writer, counters, question_mapping):
    queue = asyncio.Queue(maxsize=QUEUE_MAXSIZE)
    rate_limiter = AsyncRateLimiter(REQUESTS_PER_SECOND)
    prod = asyncio.create_task(producer(queue, payloads))
    cons = [
        asyncio.create_task(
            consumer(queue, writer, counters, question_mapping, rate_limiter)
        )
        for _ in range(CONCURRENCY)
    ]
    await prod
    await asyncio.gather(*cons)


def run_pipeline():
    start = time.time()
    question_mapping = load_question_mapping()

    # =========================================================
    # ELIGIBILITY: a question may be published only if its migration
    # (create/putDraft) call settled with status 200, 201, or 409 in the
    # migration report for this batch (DRAFT_REPORT_DIR). This is the sole
    # eligibility source - the old published-list (docs/TO_PUBLISHED CSVs)
    # gate has been removed.
    # =========================================================
    eligible_new_ids, ids_by_status = load_migration_report_eligibility(DRAFT_REPORT_DIR)
    if not eligible_new_ids:
        Logger.error("No eligible ids found in the migration report (200/201/409) - stopping.")
        return

    # New id -> the migration status it was found under, for the [ELIGIBLE]
    # log line. Priority 200 > 201 > 409 if an id unexpectedly settled
    # under more than one status.
    id_status = {}
    for status in (409, 201, 200):
        for _id in ids_by_status[status]:
            id_status[_id] = status

    files = discover_files()
    if not files:
        Logger.error("No input files found in either folder.")
        return
    Logger.info(f"Input files: {len(files)} (across {len(INPUT_DIRS)} folders)")
    Logger.info(f"Concurrency: {CONCURRENCY}")
    Logger.info(f"Rate limit: {REQUESTS_PER_SECOND} req/s")
    Logger.info(f"Publish endpoint: {PUBLISH_DRAFT_ENDPOINT}")
    if PUBLISH_DRY_RUN:
        Logger.info("PUBLISH_DRY_RUN is set - validation only, no writes or API calls.")

    # =========================================================
    # PART 2 (local half): flip metadata.lifecycle.status to PUBLISHED, in
    # place, for every record eligible per the migration report - and only
    # those. Every other record in INPUT_DIRS is left exactly as-is (still
    # DRAFT). In PUBLISH_DRY_RUN mode this only checks/logs eligibility and
    # writes nothing (Step 12 validation pass).
    # =========================================================
    stats = EligibilityStats()
    eligible_payloads = []
    for fp in files:
        eligible_payloads.extend(
            mark_published_and_collect(
                fp, question_mapping, eligible_new_ids,
                id_status=id_status, stats=stats, dry_run=PUBLISH_DRY_RUN
            )
        )

    print("\n========================================")
    print("PUBLISH SUMMARY")
    print("========================================")
    print(f"Total transformed records : {stats.total_records:,}")
    print(f"Eligible from 200          : {len(ids_by_status[200]):,}")
    print(f"Eligible from 201          : {len(ids_by_status[201]):,}")
    print(f"Eligible from 409          : {len(ids_by_status[409]):,}")
    print(f"Total unique eligible     : {len(eligible_new_ids):,}")
    print(f"Matched eligible records  : {stats.eligible:,}")
    print(f"Already published         : {stats.already_published:,}")
    print(f"Not eligible / skipped    : {stats.not_eligible:,}")
    print(f"Missing ID mappings       : {stats.missing_mapping:,}")
    print("========================================")

    if PUBLISH_DRY_RUN:
        Logger.info("PUBLISH_DRY_RUN complete - stopping before any file write or Publish API call.")
        return

    Logger.info(
        f"Eligible for publish (status flipped to PUBLISHED locally): "
        f"{len(eligible_payloads):,}"
    )

    if not eligible_payloads:
        Logger.error("Nothing eligible to publish - stopping before any API calls.")
        return

    # =========================================================
    # PART 2 (API half): only now, after the local status flip, hit the
    # publish API - using each record's NEW id, never the old one.
    # =========================================================
    settled_ids, success_base, failed_base = build_settled_and_baseline()
    Logger.info(f"Settled mapped ids (skip): {len(settled_ids):,} | "
                f"baseline success={success_base:,} failed={failed_base:,}")

    retry_payloads = [
        p for p in eligible_payloads
        if question_mapping.get(get_qid(p)) not in settled_ids
    ]
    retry_ids = {question_mapping[get_qid(p)] for p in retry_payloads}
    Logger.info(f"To publish/retry: {len(retry_payloads):,}")

    removed = clean_nonsettled_files(retry_ids)
    Logger.info(f"Removed {removed:,} stale records from non-settled files")

    writer = StatusWriter(REPORT_DIR, MAX_CHUNK_SIZE_BYTES)
    counters = Counters(success_base, failed_base)
    try:
        asyncio.run(run_async(retry_payloads, writer, counters, question_mapping))
    finally:
        writer.flush_all()

    # =========================================================
    # Final report: how many ids are actually PUBLISHED (all-time, from
    # this script's own report dir), and the old_id/new_id mapping for
    # every one of them.
    # =========================================================
    published_mapping = collect_published_mapping(REPORT_DIR)
    published_mapping_file = os.path.join(REPORT_DIR, "published_id_mapping.json")
    with open(published_mapping_file, "w", encoding="utf-8") as f:
        json.dump(
            [
                {"old_id": old_id, "new_id": new_id}
                for new_id, old_id in sorted(published_mapping.items())
            ],
            f,
            ensure_ascii=False,
            indent=2
        )

    dur = time.time() - start
    print("\n================ DONE ================")
    print(f"New calls this run     : {counters.run_calls:,}")
    print(f"Success (total)        : {counters.success:,}")
    print(f"Failed  (total)        : {counters.failed:,}")
    print(f"Skipped unmapped       : {counters.skipped_unmapped:,}")
    print(f"Grand total            : {counters.success + counters.failed:,}")
    print(f"Published ids (all-time): {len(published_mapping):,}")
    print(f"Published id mapping    : {published_mapping_file}")
    print(f"Time                   : {dur:.2f}s"
          + (f"  ({counters.run_calls/dur:.1f} req/s)" if dur > 0 else ""))
    print("======================================")


if __name__ == "__main__":
    run_pipeline()
