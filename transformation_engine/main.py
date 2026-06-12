import os
import json
import time
import csv
import threading
from queue import Queue
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

from transformers.mcq_transformer import MCQTransformer
from transformers.msq_transformer import MSQTransformer
from transformers.img_dnd_tranformer import ImageLabellingDNDTransformer
from transformers.dropdown_transformer import DropdownTransformer
from transformers.matching_transformer import MatchingTransformer
from transformers.fib_transformer import FIBTransformer
from transformers.fib_dnd_transformer import FIBDNDTransformer
from helpers.debug_logger import DebugLogger
from helpers.csv import load_question_ids_from_csv, is_question_id_present

logger = DebugLogger()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BASE_DIR)

INPUT_ROOT = os.path.join(PROJECT_ROOT, "core_seperated_data_input")
OUTPUT_ROOT = os.path.join(BASE_DIR, "transformation_output")

FILTER_DIR = os.path.join(PROJECT_ROOT, "filter")
TERM1_FILTER_DIR = os.path.join(FILTER_DIR, "Term1_json_filtering")

BY_LO_CODE_FILE = os.path.join(TERM1_FILTER_DIR, "byLoCode.json")
BY_QUESTION_CODE_FILE = os.path.join(TERM1_FILTER_DIR, "byQuestionCode.json")

MATCHED_CSV = os.path.join(FILTER_DIR, "matched_question_ids.csv")
UNMATCHED_CSV = os.path.join(FILTER_DIR, "unmatched_question_ids.csv")
CSV_PATH = os.path.join(PROJECT_ROOT, "matched_question_ids.csv")
print_lock = threading.Lock()

def log(msg):
    with print_lock:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

log("PIPELINE STARTED")


def load_filters():
    try:
        with open(BY_LO_CODE_FILE, "r", encoding="utf-8") as f:
            lo = json.load(f)
    except:
        lo = []

    try:
        with open(BY_QUESTION_CODE_FILE, "r", encoding="utf-8") as f:
            qc = json.load(f)
    except:
        qc = []

    lo_codes = {x["loCode"] for x in lo if x.get("loCode")}

    q_codes = set()
    for i in qc:
        q_codes.update(i.get("questionCode", []))

    return lo_codes, q_codes


LO_CODES, QUESTION_CODES = load_filters()


def extract_base_code(code):
    return code.split("_Q_")[0] if "_Q_" in code else code


def contains_img(obj):
    return "<img" in str(obj).lower()


csv_queue = Queue(maxsize=10000)


def csv_worker():
    m = []
    u = []

    while True:
        item = csv_queue.get()
        if item is None:
            break

        if item["type"] == "matched":
            m.append(item["data"])
        else:
            u.append(item["data"])

        if len(m) >= 200:
            with open(MATCHED_CSV, "a", newline="", encoding="utf-8") as f:
                csv.writer(f).writerows(m)
            m.clear()

        if len(u) >= 200:
            with open(UNMATCHED_CSV, "a", newline="", encoding="utf-8") as f:
                csv.writer(f).writerows(u)
            u.clear()

    if m:
        with open(MATCHED_CSV, "a", newline="", encoding="utf-8") as f:
            csv.writer(f).writerows(m)

    if u:
        with open(UNMATCHED_CSV, "a", newline="", encoding="utf-8") as f:
            csv.writer(f).writerows(u)


def filter_question(question, question_id):
    response = question.get("response", {})
    code = response.get("code", "")

    if not code:
        csv_queue.put({"type": "unmatched", "data": [question_id, ""]})
        return False

    base = extract_base_code(code)

    if base in LO_CODES:
        csv_queue.put({
            "type": "matched",
            "data": [question_id, code, "LO_CODE", base]
        })
        return True

    if base in QUESTION_CODES:
        csv_queue.put({
            "type": "matched",
            "data": [question_id, code, "QUESTION_CODE", base]
        })
        return True

    csv_queue.put({"type": "unmatched", "data": [question_id, code]})
    return False


def get_transformer(t, raw, qid, lesson):
    if t == "MULTIPLE_CHOICE":
        return MCQTransformer(raw, qid, lesson)
    if t == "MULTIPLE_SELECTION":
        return MSQTransformer(raw, qid, lesson)
    if t == "IMAGE_LABELLING_DRAG_DROP":
        return ImageLabellingDNDTransformer(raw, qid, lesson)
    if t == "SELECT_A_BLANK":
        return DropdownTransformer(raw)
    if t == "MATCHING":
        return MatchingTransformer(raw)
    if t == "FILL_IN_THE_BLANK":
        return FIBTransformer(raw, qid, lesson)
    if t == "FILL_IN_THE_BLANK_DRAG_DROP":
        return FIBDNDTransformer(raw, qid, lesson)
    return None


def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return None


def build_tasks(root):
    tasks = []

    for lesson in os.scandir(root):
        if not lesson.is_dir():
            continue

        for file in os.scandir(lesson.path):
            if not file.is_file():
                continue
            if not file.name.endswith(".json"):
                continue

            qtype = file.name.replace(".json", "")
            tasks.append((file.path, qtype, lesson.name))

    return tasks


def process_file(task):
    path, qtype, lesson = task

    log(f"STARTED  | {path} | lesson={lesson} | type={qtype}")

    data = load_json(path)
    if not data:
        return lesson, qtype, []

    items = data if isinstance(data, list) else [data]

    out = []
    seen = set()

    for w in items:
        q = w.get("response")
        qid = w.get("question_id")

        if not q or qid in seen:
            continue

        seen.add(qid)

        if contains_img(q):
            logger.log(qid, lesson, q.get("type"), "IMAGE SKIPPED", None)
            continue

        if not is_question_id_present(qid):
            logger.log(qid, lesson, q.get("type"), "FILTERED", None)
            continue


        t = q.get("type")

        transformer = get_transformer(t, q, qid, lesson)
        if not transformer:
            continue

        res = transformer.transform()

        if res:
            out.append(res)
    return lesson, qtype, out


def init_csv():
    with open(MATCHED_CSV, "w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow(["question_id", "question_code", "match_source", "matched_value"])

    with open(UNMATCHED_CSV, "w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow(["question_id", "question_code"])


def run():
    log("START")

    init_csv()
    load_question_ids_from_csv(CSV_PATH)
    tasks = build_tasks(INPUT_ROOT)
    if not tasks:
        log("NO FILES FOUND")
        return

    workers = min(os.cpu_count() * 2, len(tasks))

    writer = threading.Thread(target=csv_worker, daemon=True)
    writer.start()

    start = time.time()
    total = 0

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = [ex.submit(process_file, t) for t in tasks]

        for f in as_completed(futures):
            lesson, qtype, data = f.result()

            path = os.path.join(OUTPUT_ROOT, lesson)
            os.makedirs(path, exist_ok=True)

            out_file = os.path.join(path, f"{qtype}.json")

            with open(out_file, "w", encoding="utf-8") as fp:
                json.dump(data, fp, ensure_ascii=False, indent=2)

            total += len(data)

            log(f"FINISHED | {lesson}/{qtype} -> records={len(data)}")

    csv_queue.put(None)
    writer.join()

    log("PIPELINE COMPLETED")
    log(f"TOTAL TIME: {time.time() - start:.2f} sec")
    log(f"TOTAL RECORDS: {total}")


if __name__ == "__main__":
    run()