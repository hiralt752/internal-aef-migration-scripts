import os
import re
import json
import argparse
from datetime import datetime
from collections import defaultdict, Counter

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_REPORT_DIR = os.path.join(BASE_DIR, "FINAL_MCQ_FIXES_PUBLISHED_API_REPORT")

PART_RE = re.compile(r"^(\d+)_part\d+\.json$")

QB_NOT_READY_TYPES = {"MATCHING"}


def norm_type(t):
    return (t or "UNKNOWN").strip()


def rank(code):
    if 200 <= code < 300:
        return 3
    if code == 409:
        return 2
    if code == 400:
        return 1
    return 0


def is_success(code):
    return (200 <= code < 300) or code == 409


def list_part_files(report_dir, recursive=False):
    out = []
    if not os.path.isdir(report_dir):
        return out

    if recursive:
        for root, _, filenames in os.walk(report_dir):
            for name in sorted(filenames):
                m = PART_RE.match(name)
                path = os.path.join(root, name)
                if m and os.path.isfile(path):
                    out.append((int(m.group(1)), path))
    else:
        for name in sorted(os.listdir(report_dir)):
            m = PART_RE.match(name)
            path = os.path.join(report_dir, name)
            if m and os.path.isfile(path):
                out.append((int(m.group(1)), path))

    return sorted(out, key=lambda item: item[1])


def read_records(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else [data]
    except Exception:
        return []


def is_pending(code, qtype):
    return code == 400 and norm_type(qtype).upper() in QB_NOT_READY_TYPES


def parse_args():
    parser = argparse.ArgumentParser(
        description="Generate an aggregate API migration report from NNN_part*.json files."
    )
    parser.add_argument(
        "report_dir",
        nargs="?",
        default=DEFAULT_REPORT_DIR,
        help="Folder containing API report part files.",
    )
    parser.add_argument(
        "--recursive",
        action="store_true",
        help="Scan nested batch folders under report_dir.",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    report_dir = os.path.abspath(args.report_dir)
    part_files = list_part_files(report_dir, recursive=args.recursive)
    if not part_files:
        print(f"[ERROR] No NNN_part*.json files found in {report_dir}")
        return

    raw_records = 0
    files_scanned = 0
    best = {} 
    batch_stats = defaultdict(lambda: Counter({"files": 0, "raw_records": 0}))

    for code, path in part_files:
        files_scanned += 1
        batch_name = os.path.relpath(os.path.dirname(path), report_dir)
        if batch_name == ".":
            batch_name = os.path.basename(report_dir)
        batch_stats[batch_name]["files"] += 1
        for rec in read_records(path):
            if not isinstance(rec, dict):
                continue
            raw_records += 1
            batch_stats[batch_name]["raw_records"] += 1
            qid = rec.get("question_id")
            if not qid:
                continue
            qtype = norm_type(rec.get("question_type"))
            r = rank(code)
            if qid not in best or r > best[qid][0]:
                best[qid] = [r, code, qtype]

    type_stats = defaultdict(lambda: {"S": 0, "F": 0, "P": 0})
    status_final = Counter()
    created = exists = bad = other_fail = pending = 0

    for qid, (r, code, qtype) in best.items():
        status_final[code] += 1

        if is_success(code):
            if 200 <= code < 300:
                created += 1
            else:
                exists += 1
            type_stats[qtype]["S"] += 1
        elif is_pending(code, qtype):
            pending += 1
            type_stats[qtype]["P"] += 1
        else:
            if code == 400:
                bad += 1
            else:
                other_fail += 1
            type_stats[qtype]["F"] += 1

    distinct = len(best)
    total_success = created + exists
    total_failed = bad + other_fail         
    dup_collapsed = raw_records - distinct

    STATUS_LABELS = {
        200: "OK", 201: "Created", 400: "Bad request", 401: "Unauthorized",
        403: "Forbidden", 404: "Not found", 409: "Already exists",
        422: "Unprocessable", 429: "Rate limited", 500: "Server error",
        502: "Bad gateway", 503: "Service unavailable",
    }
    def label(c): return STATUS_LABELS.get(c, "Other")

    L = []
    L += ["=" * 72, "API MIGRATION REPORT  (aggregate of all report files)", "=" * 72]
    L.append(f"Generated : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    L.append(f"Report dir: {report_dir}")
    L.append(f"Recursive : {args.recursive}")
    L.append(f"Scanned   : {files_scanned} part files | {raw_records:,} records")
    L.append(f"Distinct question ids : {distinct:,}")
    if dup_collapsed:
        L.append(f"Duplicate entries collapsed : {dup_collapsed:,} (counted once by best outcome)")
    L += ["", "-" * 72, "OUTCOME SUMMARY", "-" * 72]
    L.append(f"  Created (2xx)            : {created:,}")
    L.append(f"  Already exists (409)     : {exists:,}")
    L.append(f"                             ---------")
    L.append(f"  TOTAL SUCCESS            : {total_success:,}   (created + already-exists)")
    L.append("")
    L.append(f"  Bad request (400)        : {bad:,}")
    L.append(f"  Other failures (401/500) : {other_fail:,}")
    L.append(f"                             ---------")
    L.append(f"  TOTAL FAILED             : {total_failed:,}   (excludes pending below)")
    L.append("")
    L.append(f"  PENDING - QB not ready   : {pending:,}")
    L.append(f"    NOTE: {', '.join(sorted(QB_NOT_READY_TYPES))} questions returned 400 because the QB")
    L.append(f"          server is not ready for this type yet (per discussion).")
    L.append(f"          They are NOT counted as failures.")
    L.append("")
    rate = (total_success / distinct * 100) if distinct else 0.0
    L.append(f"  Success rate             : {rate:.2f}%   (of {distinct:,} distinct ids)")
    L += ["", "-" * 72, "STATUS CODE BREAKDOWN (distinct ids by final status)", "-" * 72]
    for code in sorted(status_final):
        note = "  <- includes pending QB types" if code == 400 and pending else ""
        L.append(f"{code:<4} {label(code):<20}: {status_final[code]:,}{note}")
    if len(batch_stats) > 1:
        L += ["", "-" * 72, "SOURCE BATCHES (raw records before duplicate collapse)", "-" * 72]
        batch_w = max(len(name) for name in batch_stats)
        for batch_name in sorted(batch_stats):
            stats = batch_stats[batch_name]
            L.append(
                f"{batch_name:<{batch_w}} : files {stats['files']:<3,} records {stats['raw_records']:,}"
            )
    L += ["", "-" * 72, "PER QUESTION TYPE   (T total | S success | F failure | P pending)", "-" * 72]
    name_w = max((len(t) for t in type_stats), default=12)
    name_w = max(name_w, 12)
    for qtype in sorted(type_stats, key=lambda t: (-(sum(type_stats[t].values())), t)):
        s = type_stats[qtype]["S"]; f = type_stats[qtype]["F"]; p = type_stats[qtype]["P"]
        t = s + f + p
        line = f"{qtype:<{name_w}} : T {t:<7,} S {s:<7,} F {f:<7,} P {p:,}"
        if p:
            line += "   (P = pending, QB server not ready)"
        L.append(line)
    L += ["", "-" * 72, "FAILURE DETAIL (by final status, pending excluded)", "-" * 72]
    fail_codes = [c for c in status_final if not is_success(c)]
    any_fail = False
    for code in sorted(fail_codes):
        if code == 400:
            n = bad 
        else:
            n = status_final[code]
        if n:
            any_fail = True
            L.append(f"{code:<4} {label(code):<20}: {n:,}")
    if any_fail:
        L.append(f"                          ---------")
        L.append(f"  TOTAL FAILED        : {total_failed:,}")
    else:
        L.append("None.")
    L.append("=" * 72)

    report_text = "\n".join(L)
    out_path = os.path.join(
        report_dir, f"aggregate_report_{datetime.now().strftime('%Y_%m_%d_%H_%M_%S')}.txt")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(report_text)

    print(report_text)
    print(f"\nReport written -> {out_path}")


if __name__ == "__main__":
    main()
