import os
import re
import sys
import json
import mmap
import logging
import argparse
import multiprocessing
import csv
from pathlib import Path
from datetime import datetime
from collections import defaultdict

# ---------------------------------------------------------------------------
# Pre-screen regex  — byte-level fast check
# We look for the literal bytes "passage" inside the file before any parsing.
# ---------------------------------------------------------------------------
PASSAGE_RE = re.compile(rb'"passage"', re.IGNORECASE)

PASSAGE_SCHEMA_KEYS = {
    "id", "code", "title", "language", "curriculumId",
    "gradeId", "subjectId", "content", "createdBy", "createdAt",
    "updatedBy", "updatedAt", "isExpanded", "organisations",
}


def file_has_passage(path: str) -> bool:
    """
    Fast mmap byte-scan. Returns False immediately if the file contains
    no 'passage' key at all — avoids any JSON parsing overhead.
    """
    try:
        with open(path, "rb") as fh:
            size = os.path.getsize(path)
            if size == 0:
                return False
            with mmap.mmap(fh.fileno(), 0, access=mmap.ACCESS_READ) as mm:
                return PASSAGE_RE.search(mm) is not None
    except Exception:
        return True  # if mmap fails, let the JSON parser decide


# ---------------------------------------------------------------------------
# Safe deep-get helpers
# ---------------------------------------------------------------------------

def safe_get(obj, *keys):
    """
    Navigate nested dict/list safely.
    E.g. safe_get(record, "response", "body", "passage")
    Returns the value or a sentinel _MISSING.
    """
    _MISSING = object()
    cur = obj
    for k in keys:
        if isinstance(cur, dict):
            cur = cur.get(k, _MISSING)
        elif isinstance(cur, list) and isinstance(k, int):
            cur = cur[k] if 0 <= k < len(cur) else _MISSING
        else:
            return _MISSING
        if cur is _MISSING:
            return _MISSING
    return cur


_MISSING_SENTINEL = object()


def get_passage(record: dict):
    """
    Returns:
        (value, found)
        found=True  → key path response.body.passage was present (value may be None)
        found=False → key path was entirely absent from the record
    """
    resp = record.get("response")
    if not isinstance(resp, dict):
        return None, False

    body = resp.get("body")
    if not isinstance(body, dict):
        return None, False

    if "passage" not in body:
        return None, False

    return body["passage"], True


# ---------------------------------------------------------------------------
# Question-id / type extractors  (same logic as find_html_tables.py)
# ---------------------------------------------------------------------------

def get_qid(record: dict) -> str:
    qid = record.get("question_id")
    if qid:
        return str(qid)
    resp = record.get("response")
    if isinstance(resp, dict):
        qid = resp.get("id") or resp.get("question_id")
        if qid:
            return str(qid)
    return record.get("id", "UNKNOWN")


def get_qtype(record: dict) -> str:
    resp = record.get("response")
    if isinstance(resp, dict):
        qtype = resp.get("type")
        if qtype:
            return str(qtype)
    return str(record.get("type", "UNKNOWN"))


def get_language(record: dict) -> str:
    """
    Try multiple common locations for the language field:
      record["language"]
      record["response"]["language"]
      record["response"]["body"]["passage"]["language"]  (if passage present)
    """
    lang = record.get("language")
    if lang:
        return str(lang)
    resp = record.get("response")
    if isinstance(resp, dict):
        lang = resp.get("language")
        if lang:
            return str(lang)
        body = resp.get("body")
        if isinstance(body, dict):
            passage = body.get("passage")
            if isinstance(passage, dict):
                lang = passage.get("language")
                if lang:
                    return str(lang)
    return "UNKNOWN"


# ---------------------------------------------------------------------------
# Per-record processor
# ---------------------------------------------------------------------------

def process_record(record: dict, include_null: bool, lang_filter: str, type_filter: str):
    """
    Returns a result dict or None (skip this record).

    Output dict:
    {
        "question_id"    : str,
        "question_type"  : str,
        "language"       : str,
        "passage_status" : "present" | "null",
        "passage"        : dict | None
    }
    """
    passage_val, found = get_passage(record)

    if not found:
        return None  # No passage key at all — skip

    qtype = get_qtype(record)
    lang  = get_language(record)

    # Apply optional filters
    if lang_filter  and lang  != lang_filter:
        return None
    if type_filter  and qtype != type_filter:
        return None

    if passage_val is None:
        if not include_null:
            return None
        status = "null"
    elif isinstance(passage_val, dict):
        status = "present"
    else:
        # Unexpected type — treat as present but non-standard
        status = "present"

    return {
        "question_id" : get_qid(record),
        "passage"     : passage_val,
    }


# ---------------------------------------------------------------------------
# Per-file worker  (runs in a subprocess via multiprocessing.Pool)
# ---------------------------------------------------------------------------

def process_file(task: tuple):
    """
    task = (input_path, input_dir, output_dir, include_null, lang_filter, type_filter)

    Returns (input_path, n_present, n_null, n_skipped, error_or_None,
             stats_dict: {(lang, qtype): {"present": int, "null": int}},
             passage_ids: set of unique passage["id"] values seen in this file)
    """
    import ijson

    (input_path, input_dir, output_dir,
     include_null, lang_filter, type_filter) = task

    rel      = os.path.relpath(input_path, input_dir)
    out_path = os.path.join(output_dir, rel)

    stats: dict = defaultdict(lambda: {"present": 0, "null": 0})

    try:
        os.makedirs(os.path.dirname(out_path), exist_ok=True)

        # ── 1. mmap pre-screen ──────────────────────────────────────────────
        if not file_has_passage(input_path):
            with open(out_path, "w", encoding="utf-8") as fh:
                fh.write("[]\n")
            return (input_path, 0, 0, 0, None, {}, set())

        # ── 2. Stream records with ijson ────────────────────────────────────
        results      : list = []
        seen_ids     : set  = set()
        passage_ids  : set  = set()   # unique passage["id"] values
        n_present = 0
        n_null    = 0
        n_skipped = 0

        with open(input_path, "rb") as fh:
            first_byte = b""
            while not first_byte.strip():
                first_byte = fh.read(1)
                if not first_byte:
                    break
            fh.seek(0)

            if first_byte == b"[":
                parser = ijson.items(fh, "item", use_float=True)
            else:
                parser = [json.load(fh)]

            for record in parser:
                result = process_record(record, include_null, lang_filter, type_filter)

                if result is None:
                    n_skipped += 1
                    continue

                qid = result["question_id"]

                if result["passage"] is not None:
                    n_present += 1
                    # Track unique passage IDs
                    pid = result["passage"].get("id") if isinstance(result["passage"], dict) else None
                    if pid:
                        passage_ids.add(str(pid))
                else:
                    n_null += 1

                if qid in seen_ids:
                    # Duplicate: keep the one with a present passage (prefer data)
                    for existing in results:
                        if existing["question_id"] == qid:
                            if existing["passage"] is None and result["passage"] is not None:
                                existing.update(result)
                            break
                else:
                    seen_ids.add(qid)
                    results.append(result)

        # ── 3. Write output ─────────────────────────────────────────────────
        with open(out_path, "w", encoding="utf-8") as fh:
            json.dump(results, fh, indent=2, ensure_ascii=False)
            fh.write("\n")

        return (input_path, n_present, n_null, n_skipped, None, dict(stats), passage_ids)

    except json.JSONDecodeError as exc:
        try:
            with open(out_path, "w", encoding="utf-8") as fh:
                fh.write("[]\n")
        except Exception:
            pass
        return (input_path, 0, 0, 0, f"JSON parse error: {exc}", {}, set())

    except Exception as exc:
        try:
            with open(out_path, "w", encoding="utf-8") as fh:
                fh.write("[]\n")
        except Exception:
            pass
        return (input_path, 0, 0, 0, f"Unexpected error: {exc}", {}, set())


# ---------------------------------------------------------------------------
# Collect all .json files
# ---------------------------------------------------------------------------

def collect_json_files(root: str):
    for dirpath, _dirs, files in os.walk(root):
        for fname in files:
            if fname.lower().endswith(".json"):
                yield os.path.join(dirpath, fname)


# ---------------------------------------------------------------------------
# Inline progress bar  +  live counters
# ---------------------------------------------------------------------------

class Bar:
    def __init__(self, total: int):
        self.total          = total
        self.done           = 0
        self.skipped        = 0
        self.n_present      = 0   # total question_ids written to output
        self.n_null         = 0
        self.errors         = 0
        self.unique_passages = 0  # unique passage IDs seen globally
        self._W             = 38
        # We print 2 lines; need to overwrite both on each update
        self._first_render  = True

    def update(self, n_present: int, n_null: int, has_error: bool,
               was_skipped: bool, new_unique_passages: int):
        self.done            += 1
        self.n_present       += n_present
        self.n_null          += n_null
        self.unique_passages += new_unique_passages
        if has_error:
            self.errors += 1
        if was_skipped:
            self.skipped += 1
        self._render()

    def _render(self):
        pct    = self.done / self.total if self.total else 1
        filled = int(self._W * pct)
        bar    = "█" * filled + "░" * (self._W - filled)

        line1 = (
            f"[{bar}] {self.done}/{self.total} files  "
            f"| skipped:{self.skipped}  "
            f"| err:{self.errors}"
        )
        line2 = (
            f"  📝  question_ids in output : {self.n_present:>10,}   "
            f"(null passage: {self.n_null:,})\n"
            f"  🔖  unique passages        : {self.unique_passages:>10,}"
        )

        if not self._first_render:
            # Move cursor up 3 lines to overwrite previous block
            sys.stdout.write("\033[3A")

        sys.stdout.write(f"\r{line1}\n{line2}\n")
        sys.stdout.flush()
        self._first_render = False

        if self.done == self.total:
            print()   # final newline after last render


# ---------------------------------------------------------------------------
# Write summary TSV
# ---------------------------------------------------------------------------

def write_summary(output_dir: str, global_stats: dict):
    """
    global_stats: { (lang, qtype): {"present": int, "null": int} }
    Writes a TSV: output_dir/passage_summary.tsv
    """
    tsv_path = os.path.join(output_dir, "passage_summary.tsv")
    rows = []
    for (lang, qtype), counts in sorted(global_stats.items()):
        present = counts["present"]
        null_c  = counts["null"]
        total   = present + null_c
        rows.append((lang, qtype, total, present, null_c))

    rows.sort(key=lambda r: (r[0], r[1]))

    with open(tsv_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh, delimiter="\t")
        writer.writerow(["language", "question_type", "total", "present", "null"])
        writer.writerows(rows)

    print(f"\n  📊 Summary TSV written to: {tsv_path}")
    print(f"\n  {'language':<12} {'question_type':<45} {'total':>8} {'present':>8} {'null':>8}")
    print(f"  {'-'*12} {'-'*45} {'-'*8} {'-'*8} {'-'*8}")
    for lang, qtype, total, present, null_c in rows:
        print(f"  {lang:<12} {qtype:<45} {total:>8,} {present:>8,} {null_c:>8,}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(
        description="Extract passage data from response.body.passage in JSON question files.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument("input_dir",  help="Root input folder (e.g. unique_record/)")
    ap.add_argument("output_dir", help="Root output folder (mirrored structure)")
    ap.add_argument(
        "--workers", "-w",
        type=int,
        default=min(multiprocessing.cpu_count(), 8),
        help="Parallel worker processes (default: min(cpu_count, 8))",
    )
    ap.add_argument(
        "--include-null",
        action="store_true",
        default=False,
        help="Also emit records where passage is null (default: only non-null passages)",
    )
    ap.add_argument(
        "--lang",
        default="",
        help="Filter to a specific language code, e.g. --lang ar",
    )
    ap.add_argument(
        "--type",
        dest="qtype",
        default="",
        help="Filter to a specific question type, e.g. --type MULTIPLE_CHOICE",
    )
    ap.add_argument(
        "--log", "-l",
        default="find_passages.log",
        help="Log file (default: find_passages.log)",
    )
    args = ap.parse_args()

    # ── Logging ──────────────────────────────────────────────────────────────
    logging.basicConfig(
        filename=args.log, filemode="w",
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    log = logging.getLogger(__name__)

    input_dir  = os.path.abspath(args.input_dir)
    output_dir = os.path.abspath(args.output_dir)

    if not os.path.isdir(input_dir):
        sys.exit(f"[ERROR] Input directory not found: {input_dir}")

    os.makedirs(output_dir, exist_ok=True)

    # ── Collect files ─────────────────────────────────────────────────────────
    print(f"\n{'='*72}")
    print(f"  Passage Extractor  (streaming + mmap + multiprocessing)")
    print(f"  Input        : {input_dir}")
    print(f"  Output       : {output_dir}")
    print(f"  Workers      : {args.workers}")
    print(f"  Include null : {args.include_null}")
    print(f"  Lang filter  : {args.lang or '(all)'}")
    print(f"  Type filter  : {args.qtype or '(all)'}")
    print(f"  Log          : {os.path.abspath(args.log)}")
    print(f"{'='*72}")
    print("Scanning for JSON files …", end=" ", flush=True)

    json_files = sorted(collect_json_files(input_dir),
                        key=lambda p: os.path.getsize(p))
    total    = len(json_files)
    total_mb = sum(os.path.getsize(f) for f in json_files) / 1_048_576
    print(f"{total:,} files found ({total_mb:,.0f} MB total).\n")
    log.info("Files found: %d  Total size: %.0f MB  Workers: %d",
             total, total_mb, args.workers)

    if total == 0:
        sys.exit("[INFO] No JSON files found.")

    tasks = [
        (f, input_dir, output_dir, args.include_null, args.lang, args.qtype)
        for f in json_files
    ]

    bar                  = Bar(total)
    global_stats : dict  = defaultdict(lambda: {"present": 0, "null": 0})
    # Global set of unique passage IDs across all files
    all_passage_ids      : set = set()
    start                = datetime.now()

    with multiprocessing.Pool(processes=args.workers) as pool:
        for (input_path, n_present, n_null, n_skipped,
             err, file_stats, passage_ids) in pool.imap_unordered(
            process_file, tasks, chunksize=2
        ):
            was_skipped = (n_present == 0 and n_null == 0 and err is None)

            # Count only *newly seen* passage IDs to avoid double-counting
            new_unique = len(passage_ids - all_passage_ids)
            all_passage_ids |= passage_ids

            bar.update(n_present, n_null, err is not None, was_skipped, new_unique)

            # Merge per-file stats into global stats
            for key, counts in file_stats.items():
                global_stats[key]["present"] += counts["present"]
                global_stats[key]["null"]    += counts["null"]

            if err:
                log.error("%-80s  →  %s", input_path, err)
            elif n_present or n_null:
                rel = os.path.relpath(input_path, input_dir)
                log.info("PASSAGE  %-60s  present=%d null=%d",
                         rel, n_present, n_null)

    elapsed = (datetime.now() - start).total_seconds()

    # ── Summary ───────────────────────────────────────────────────────────────
    print(f"\n{'='*72}")
    print(f"  ✅  COMPLETE  —  {elapsed:.1f}s  ({total_mb/max(elapsed,0.01):.0f} MB/s)")
    print(f"  Files processed          : {total:>8,}")
    print(f"  Pre-screened (skip)      : {bar.skipped:>8,}  ← no 'passage' key, instant")
    print(f"  question_ids in output   : {bar.n_present:>8,}  ← records written with passage")
    print(f"  Unique passages          : {bar.unique_passages:>8,}  ← distinct passage IDs")
    print(f"  Records null passage     : {bar.n_null:>8,}")
    print(f"  Errors                   : {bar.errors:>8,}")
    print(f"{'='*72}")

    if global_stats:
        write_summary(output_dir, global_stats)

    log.info("DONE  files=%d skipped=%d present=%d unique_passages=%d null=%d errors=%d elapsed=%.1fs",
             total, bar.skipped, bar.n_present, bar.unique_passages, bar.n_null, bar.errors, elapsed)


if __name__ == "__main__":
    main()