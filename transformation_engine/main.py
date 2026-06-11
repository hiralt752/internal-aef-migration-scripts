import os
import json
import time
import asyncio
from concurrent.futures import ThreadPoolExecutor, as_completed
 
from transformers.mcq_transformer import MCQTransformer
from transformers.msq_transformer import MSQTransformer
from transformers.img_dnd_tranformer import ImageLabellingDNDTransformer
from transformers.dropdown_transformer import DropdownTransformer
from transformers.matching_transformer import MatchingTransformer
from transformers.fib_transformer import FIBTransformer
# from transformers.dnd_transformer import DNDTransformer
from transformers.fib_dnd_transformer import FIBDNDTransformer
from helpers.contains_img_tag import contains_img_tag
from helpers.debug_logger import DebugLogger

logger = DebugLogger()
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BASE_DIR)

INPUT_ROOT = os.path.join(
    PROJECT_ROOT,
    "core_seperated_data_input"
)

OUTPUT_ROOT = os.path.join(
    BASE_DIR,
    "transformation_output"
)

TARGET_FILES = frozenset()

print("🚀 TRANSFORMATION PIPELINE STARTED")
def contains_img_tag(value) -> bool:
 
    if isinstance(value, str):
        return "<img" in value.lower()
 
    if isinstance(value, dict):
        return any(contains_img_tag(v) for v in value.values())
 
    if isinstance(value, list):
        return any(contains_img_tag(item) for item in value)
 
    return False
 
def get_transformer(question_type, raw,question_id,lesson):
 
    if question_type == "MULTIPLE_CHOICE":
        return MCQTransformer(raw,question_id,lesson)
    if question_type == "MULTIPLE_SELECTION":
        return MSQTransformer(raw,question_id,lesson)
    if question_type == "IMAGE_LABELLING_DRAG_DROP":
        return ImageLabellingDNDTransformer(raw,question_id,lesson)
    if question_type == "SELECT_A_BLANK":
        return DropdownTransformer(raw)
    if question_type == "MATCHING":
        return MatchingTransformer(raw)
    if question_type == "FILL_IN_THE_BLANK":
        return FIBTransformer(raw,question_id,lesson)
    if question_type == "FILL_IN_THE_BLANK_DRAG_DROP":
        return FIBDNDTransformer(raw,question_id,lesson)
    return None
 
 
def load_json(file_path):
 
    try:
        with open(
            file_path,
            "r",
            encoding="utf-8"
        ) as f:
 
            return json.load(f)
 
    except Exception as e:
 
        print(f"❌ Failed reading {file_path}")
        print(e)
 
        return None
 
 
def build_tasks():
 
    tasks = []
 
    try:
        with os.scandir(INPUT_ROOT) as top:
 
            for lesson_entry in top:
 
                if not lesson_entry.is_dir(follow_symlinks=False):
                    continue
 
                with os.scandir(lesson_entry.path) as sub:
 
                    for file_entry in sub:
 
                        if not file_entry.is_file():
                            continue
                       
                        if TARGET_FILES:
                            if file_entry.name not in TARGET_FILES:
                                continue
                        else:
                            if not file_entry.name.endswith(".json"):
                                continue
 
                        qtype = file_entry.name.replace(".json", "")
 
                        tasks.append(
                            (
                                file_entry.path,
                                qtype,
                                lesson_entry.name
                            )
                        )
 
    except Exception as e:
        print(f"❌ Error building tasks: {e}")
 
    return tasks
 
def process_single_file(task):
 
    file_path, qtype, lesson = task
 
    print(f"▶️ START: {file_path}")
 
    start = time.time()
 
    data = load_json(file_path)
 
    if not data:
        return {
            "lesson": lesson,
            "qtype": qtype,
            "data": []
        }
 
    items = data if isinstance(data, list) else [data]
 
    transformed = []
    seen_question_ids = set()
 
    MAX_PER_QT = 5
    count = 0
 
    for wrapper in items:
 
        try:
 
            if count >= MAX_PER_QT:
                break
 
            question = wrapper.get("response")
            question_id = wrapper.get("question_id")
 
            if question_id:
 
                if question_id in seen_question_ids:
                    continue
 
                seen_question_ids.add(question_id)
 
            if not question:
                continue
 
            question_type = question.get("type")
 
            if contains_img_tag(question):
 
                logger.log(
                    question_id=question_id,
                    lesson=lesson,
                    question_type=question_type,
                    reason="Question has Image in it",
                    file_path=None
                )
 
                continue
 
            transformer = get_transformer(
                question_type,
                question,
                question_id,
                lesson
            )
 
            if transformer is None:
                continue
 
            transformed_question = transformer.transform()
 
            if transformed_question:
 
                transformed.append(
                    transformed_question
                )
 
                count += 1
 
        except Exception as e:
 
            print(
                f"❌ Transform Failed | "
                f"{wrapper.get('question_id')} | "
                f"{e}"
            )
 
    elapsed = time.time() - start
 
    print(
        f"✅ DONE: {file_path} | "
        f"{elapsed:.2f}s | "
        f"{len(transformed)} records"
    )
 
    return {
        "lesson": lesson,
        "qtype": qtype,
        "data": transformed
    }
def run_transformation_pipeline():
 
    print("\n" + "=" * 60)
    print("🚀 TRANSFORMATION PIPELINE STARTED")
    print("=" * 60)
 
    os.makedirs(
        OUTPUT_ROOT,
        exist_ok=True
    )
 
    tasks = build_tasks()
 
    if not tasks:
 
        print("❌ No files found")
        return
 
    print(f"⚡ Files Found : {len(tasks)}")
 
    workers = min(
        os.cpu_count() or 4,
        len(tasks)
    )
 
    print(f"🚀 Workers     : {workers}")
 
    start_pipeline = time.time()
 
    total_records = 0
 
    with ThreadPoolExecutor(
        max_workers=workers,
        thread_name_prefix="Transformer"
    ) as executor:
 
        futures = {
            executor.submit(
                process_single_file,
                task
            ): task
            for task in tasks
        }
 
        for future in as_completed(futures):
 
            try:
 
                result = future.result()
 
                lesson = result["lesson"]
                qtype = result["qtype"]
                data = result["data"]
 
                lesson_dir = os.path.join(
                    OUTPUT_ROOT,
                    lesson
                )
 
                os.makedirs(
                    lesson_dir,
                    exist_ok=True
                )
 
                output_file = os.path.join(
                    lesson_dir,
                    f"{qtype}.json"
                )
 
                with open(
                    output_file,
                    "w",
                    encoding="utf-8"
                ) as f:
 
                    json.dump(
                        data,
                        f,
                        indent=2,
                        ensure_ascii=False
                    )
 
                total_records += len(data)
 
                print(
                    f"💾 Saved: "
                    f"{lesson}/{qtype}.json "
                    f"({len(data)} records)"
                )
 
            except Exception as ex:
 
                print(f"❌ ERROR: {ex}")
 
    elapsed = time.time() - start_pipeline
 
    print("\n" + "=" * 60)
    print("✅ PIPELINE COMPLETE")
    print("=" * 60)
    print(f"⏱️ Total Time    : {elapsed:.2f}s")
    print(f"📊 Total Records : {total_records}")
 
 
if __name__ == "__main__":
    run_transformation_pipeline()