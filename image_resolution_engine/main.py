import json
import os
import time
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed

from helpers.common_filter import should_skip_question
from analyzers.dispatcher import analyze_question
from helpers.file_loader import load_json
from helpers.resolution_debugger import log_skip, log_success


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BASE_DIR)

INPUT_ROOT = os.path.join(PROJECT_ROOT, "core_seperated_data_input")
OUTPUT_ROOT = os.path.join(BASE_DIR, "image_resolution_output")

TARGET_FILES = frozenset()

print("🚀 PIPELINE STARTED")


# -----------------------------
# WORKER FUNCTION (PROCESS SAFE)
# -----------------------------
MAX_RECORDS_PER_FILE = 10
def process_single_file(task):
    file_path, qtype, category = task

    print(f"▶️ START: {file_path}")
    start = time.time()

    data = load_json(file_path)
    if not data:
        return []

    items = data if isinstance(data, list) else [data]

    # LIMIT HERE 👇
    items = items[:MAX_RECORDS_PER_FILE]

    results = []

    for item in items:
        qid = item.get("question_id")
        question_type = item.get("response", {}).get("type")
        lesson = category or item.get("lesson") or item.get("category")

        res = analyze_question(item, question_type, category)

        if not res:
            log_skip(
                question_id=qid,
                stage="ANALYZER",
                reason="ANALYZER",
                question_type=qtype,
                lesson=lesson
            )
            continue

        log_success(
            question_id=qid,
            widget_type=res.get("widget_type"),
            resolution=res.get("resolution"),
            question_type=qtype,
            lesson=lesson
        )

        results.append(res)

    elapsed = time.time() - start
    print(f"✅ DONE: {file_path} | {elapsed:.2f}s | {len(results)} results")

    return results

# -----------------------------
# TASK BUILDER
# -----------------------------
def build_tasks():
    tasks = []

    try:
        with os.scandir(INPUT_ROOT) as top:
            for cat_entry in top:
                if not cat_entry.is_dir():
                    continue

                with os.scandir(cat_entry.path) as sub:
                    for file_entry in sub:

                        if not file_entry.is_file():
                            continue

                        if TARGET_FILES and file_entry.name not in TARGET_FILES:
                            continue

                        qtype = file_entry.name.replace(".json", "")

                        tasks.append((
                            file_entry.path,
                            qtype,
                            cat_entry.name
                        ))

    except Exception as e:
        print(f"❌ Error building tasks: {e}")

    return tasks


# -----------------------------
# MAIN PIPELINE
# -----------------------------
def run_pipeline():
    print("\n" + "=" * 40)
    print("🚀 RUN PIPELINE STARTED")
    print("=" * 40)

    os.makedirs(OUTPUT_ROOT, exist_ok=True)

    tasks = build_tasks()
    if not tasks:
        print("❌ No tasks found!")
        return

    print(f"⚡ Files: {len(tasks)}")

    workers = max(1, os.cpu_count())
    print(f"🚀 Workers: {workers}\n")

    start_pipeline = time.time()

    grouped_output = defaultdict(list)
    total_processed = 0

    # -----------------------------
    # PROCESS POOL (TRUE PARALLEL)
    # -----------------------------
    with ProcessPoolExecutor(max_workers=workers) as executor:

        futures = [executor.submit(process_single_file, task) for task in tasks]

        for future in as_completed(futures):
            try:
                results = future.result()
                total_processed += len(results)

                for r in results:
                    grouped_output[r.get("source_type", "unknown")].append(r)

            except Exception as ex:
                print(f"❌ ERROR: {ex}")

    # -----------------------------
    # WRITE OUTPUT
    # -----------------------------
    total_output_records = 0

    for qtype, items in grouped_output.items():
        out_file = os.path.join(OUTPUT_ROOT, f"{qtype}.json")

        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(items, f, indent=2, ensure_ascii=False)

        print(f"💾 {qtype}: {len(items)} items")
        total_output_records += len(items)

    elapsed = time.time() - start_pipeline

    print("\n✅ DONE!")
    print(f"⏱ Total time: {elapsed:.2f}s")
    print(f"📊 Total processed: {total_processed}")
    print(f"📦 Output records: {total_output_records}")


if __name__ == "__main__":
    run_pipeline()