import os
import json
import sys
import csv
import re
import requests
import urllib.parse
from pathlib import Path
from collections import defaultdict
from datetime import datetime, timezone
from PIL import Image
import signal
from transformation_engine.config import settings
from transformation_engine.helpers.debug_logger import DebugLogger
from image_resolution_engine.analyzers.dispatcher import analyze_question
from image_resolution_engine.helpers.resolution_debugger import log_skip, log_success

shutdown_requested = False

# BASE_URL="https://shared.alefed.com" #PROD url
BASE_URL="https://ccl-rc-az.nprd.alefed.com" #DEV url 

def signal_handler(sig, frame):
    global shutdown_requested
    if shutdown_requested:
        print("\n[!] Force exiting...")
        sys.exit(1)
    print("\n[!] Interrupt received! Finishing current question and saving progress...")
    shutdown_requested = True

# Ensure the root directory is in the path to import the logger and other engines
BASE_DIR = os.path.dirname(os.path.abspath(__file__)) #get the current script's directory
sys.path.append(BASE_DIR)
sys.path.append(os.path.join(BASE_DIR, "image_resolution_engine"))

INPUT_DIR = f"{BASE_DIR}\core_seperated_data_input"
OUTPUT_DIR = f"{BASE_DIR}\image_resolution_engine\image_resolution_output"
STAGE_RECORD_FILE = f"{BASE_DIR}\stage_record.json"

# ============================================================
# Filter Engine Logic & Paths
# ============================================================
# FILTER_DIR = Path(r"C:\Users\trupa\OneDrive\Desktop\Alef\migration\filter")
# TERM1_FILTER_DIR = FILTER_DIR / "Term1_json_filtering"
# BY_LO_CODE_FILE = TERM1_FILTER_DIR / "byLoCode.json"
# BY_QUESTION_CODE_FILE = TERM1_FILTER_DIR / "byQuestionCode.json"
# MATCHED_CSV = FILTER_DIR / "matched_question_ids.csv"
# UNMATCHED_CSV = FILTER_DIR / "unmatched_question_ids.csv"

# try:
#     with open(BY_LO_CODE_FILE, "r", encoding="utf-8") as file:
#         lo_code_data = json.load(file)
# except FileNotFoundError:
#     print(f"Warning: {BY_LO_CODE_FILE.name} not found.")
#     lo_code_data = []

# try:
#     with open(BY_QUESTION_CODE_FILE, "r", encoding="utf-8") as file:
#         question_code_data = json.load(file)
# except FileNotFoundError:
#     print(f"Warning: {BY_QUESTION_CODE_FILE.name} not found.")
#     question_code_data = []

# LO_CODES = {item["loCode"] for item in lo_code_data if item.get("loCode")}
# QUESTION_CODES = set()
# for subject_data in question_code_data:
#     QUESTION_CODES.update(subject_data.get("questionCode", []))

# def _initialize_csv_files() -> None:
#     with open(MATCHED_CSV, "w", newline="", encoding="utf-8") as file:
#         writer = csv.writer(file)
#         writer.writerow(["question_id", "question_code", "match_source", "matched_value"])
#     with open(UNMATCHED_CSV, "w", newline="", encoding="utf-8") as file:
#         writer = csv.writer(file)
#         writer.writerow(["question_id", "question_code"])

# _initialize_csv_files()

# def _append_matched_record(question_id: str, question_code: str, match_source: str, matched_value: str) -> None:
#     with open(MATCHED_CSV, "a", newline="", encoding="utf-8") as file:
#         writer = csv.writer(file)
#         writer.writerow([question_id, question_code, match_source, matched_value])

# def _append_unmatched_record(question_id: str, question_code: str) -> None:
#     with open(UNMATCHED_CSV, "a", newline="", encoding="utf-8") as file:
#         writer = csv.writer(file)
#         writer.writerow([question_id, question_code])

# def _extract_base_code(question_code: str) -> str:
#     if "_Q_" in question_code:
#         return question_code.split("_Q_")[0]
#     return question_code

# def filter_question(question: dict) -> bool:
#     question_id = question.get("question_id", "")
#     response_block = question.get("response", {})
#     question_code = response_block.get("code", "")

#     if not question_code:
#         _append_unmatched_record(question_id, question_code)
#         return False

#     base_code = _extract_base_code(question_code)

#     if base_code in LO_CODES:
#         _append_matched_record(question_id=question_id, question_code=question_code, match_source="LO_CODE", matched_value=base_code)
#         return True

#     if base_code in QUESTION_CODES:
#         _append_matched_record(question_id=question_id, question_code=question_code, match_source="QUESTION_CODE", matched_value=base_code)
#         return True

#     _append_unmatched_record(question_id=question_id, question_code=question_code)
#     return False

def process_next_stage(question: dict, category: str):
    question_type = question.get("response", {}).get("type")
    res = analyze_question(question, question_type, category)
    
    qid = question.get("question_id")
    lesson = category or question.get("lesson") or question.get("category")
    
    if not res:
        log_skip(question_id=qid, stage="ANALYZER", reason="ANALYZER", question_type=question_type, lesson=lesson)
        return None

    log_success(question_id=qid, widget_type=res.get("widget_type"), resolution=res.get("resolution"), question_type=question_type, lesson=lesson)
    return res

def process_image(image_path, output_path, target_width, target_height):
    PADDING_COLOR = (255, 255, 255)
    try:
        with Image.open(image_path) as img:
            img = img.convert("RGB")
            original_width, original_height = img.size

            scale = min(target_width / original_width, target_height / original_height)
            new_width = int(original_width * scale)
            new_height = int(original_height * scale)

            resized = img.resize((new_width, new_height), Image.LANCZOS)
            canvas = Image.new("RGB", (target_width, target_height), PADDING_COLOR)

            x_offset = (target_width - new_width) // 2
            y_offset = (target_height - new_height) // 2

            canvas.paste(resized, (x_offset, y_offset))
            canvas.save(output_path, quality=95)
            return os.path.basename(output_path), os.path.getsize(output_path)
    except Exception as e:
        print(f"   -> [ERROR] Failed processing {image_path}: {e}")
        return None, 0

def update_json_file(file_path, key, data):
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = json.load(f)
    except Exception:
        content = {}
        
    content[key] = data
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(content, f, indent=2)

def upload_single_image(file_path: str, file_name: str, file_size: int, content_type: str) -> str:
    headers_auth = {
        "Authorization": settings.BEARER_TOKEN,
        "X-tenantId": "shared",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Origin": f"{BASE_URL}",
        "Referer": f"{BASE_URL}/"
    }

    # Step 1: Get Presigned URL
    base_url = f"{BASE_URL}/authoring-content-service/api/assets/presigned-upload-url"
    params = {"fileName": file_name, "contentType": content_type, "fileSize": file_size}
    url_encoded = urllib.parse.urlencode(params)
    
    resp_1 = requests.get(f"{base_url}?{url_encoded}", headers=headers_auth, timeout=10)
    try:
        r1_json = resp_1.json()
    except Exception:
        r1_json = resp_1.text
        
    update_json_file(r"C:\Users\trupa\OneDrive\Desktop\Alef\migration\image_upload\step_1_responce.json", file_name, {
        "api_status": "success" if 200 <= resp_1.status_code < 300 else "failed",
        "http_code": resp_1.status_code,
        "responce": r1_json
    })
    
    step_1_data = r1_json if isinstance(r1_json, dict) else {}
    presigned_url = step_1_data.get("presignedUrl", {}).get("url")
    if not presigned_url:
        raise Exception("Presigned URL missing from response")

    # Step 2: PUT Image
    headers_put = {
        "x-ms-blob-type": "BlockBlob",
        "Content-Type": content_type
    }
    with open(file_path, "rb") as img_file:
        resp_2 = requests.put(presigned_url, headers=headers_put, data=img_file, timeout=30)

    update_json_file(r"C:\Users\trupa\OneDrive\Desktop\Alef\migration\image_upload\step_2_responce.json", file_name, {
        "api_status": "success" if 200 <= resp_2.status_code < 300 else "failed",
        "http_code": resp_2.status_code,
        "responce_text": resp_2.text
    })
    resp_2.raise_for_status()

    # Step 3: Publish
    publish_url = f"{BASE_URL}/authoring-content-service/api/assets/create-and-publish"
    file_id = step_1_data.get("fileId")
    upload_id = step_1_data.get("uploadId")
    
    try:
        last_part = file_name.split("_")[-1]
        title = os.path.splitext(last_part)[0]
    except Exception:
        title = "image_migration"
        
    publish_payload = {
        "fileName": file_name,
        "fileId": file_id,
        "uploadId": upload_id,
        "title": title,
        "description": title,
        "type": "IMAGE",
        "metadata": [],
        "systemMetadata": [],
        "tagIds": []
    }
    resp_3 = requests.post(publish_url, headers={**headers_auth, "Content-Type": "application/json"}, json=publish_payload, timeout=15)
    
    try:
        r3_json = resp_3.json()
    except Exception:
        r3_json = resp_3.text
        
    update_json_file(r"C:\Users\trupa\OneDrive\Desktop\Alef\migration\image_upload\step_3_responce.json", file_name, {
        "api_status": "success" if 200 <= resp_3.status_code < 300 else "failed",
        "http_code": resp_3.status_code,
        "responce": r3_json
    })
    
    resp_3.raise_for_status()
    step_3_data = r3_json if isinstance(r3_json, dict) else {}
    
    asset_id = step_3_data.get("assetId") or step_3_data.get("id")
    if not asset_id:
        raise Exception("Asset ID missing from publish response")
        
    return asset_id

def process_and_upload_images(res, category):
    import glob
    MEDIA_FOLDER = r"C:\Users\trupa\Downloads\Alef\media"
    TRANSFORMED_BASE_DIR = r"C:\Users\trupa\OneDrive\Desktop\Alef\migration\transformed_image"
    output_dir = os.path.join(TRANSFORMED_BASE_DIR, category)
    os.makedirs(output_dir, exist_ok=True)
    
    qid = res.get("question_id")
    resolution_data = res.get("resolution", {})
    images_to_process = []
    
    q_images = res.get("question_images", [])
    o_images = res.get("option_images", [])
    audit_images = res.get("image_audit", [])
    
    for img in q_images:
        tw = resolution_data.get("max_width", 600)
        th = resolution_data.get("max_height", 338)
        images_to_process.append((img, tw, th))
        
    for img in o_images:
        if len(q_images) > 0:
            tw = resolution_data.get("option_width", resolution_data.get("max_width", 600))
            th = resolution_data.get("option_height", resolution_data.get("max_height", 338))
        else:
            tw = resolution_data.get("max_width", 600)
            th = resolution_data.get("max_height", 338)
        images_to_process.append((img, tw, th))
        
    for img in audit_images:
        tw = img.get("max_width", 600)
        th = img.get("max_height", 338)
        images_to_process.append((img, tw, th))
    
    seen_srcs = set()
    replacement_map = {}
    
    for img, tw, th in images_to_process:
        src = img.get("src")
        if src and src not in seen_srcs:
            seen_srcs.add(src)
            image_name = src.replace("\\", "/").split("/")[-1]
            search_pattern = os.path.join(MEDIA_FOLDER, "**", f"{qid}*{image_name}")
            matching_files = glob.glob(search_pattern, recursive=True)
            
            if matching_files:
                original_file_name = os.path.basename(matching_files[0])
                output_path = os.path.join(output_dir, original_file_name)
                fname, fsize = process_image(matching_files[0], output_path, int(tw), int(th))
                
                if fname:
                    ext = os.path.splitext(fname)[1].lower()
                    content_type = "image/jpeg" if ext in ['.jpg', '.jpeg'] else f"image/{ext.strip('.')}"
                    
                    try:
                        print(f"   -> Uploading {fname} to server...")
                        asset_id = upload_single_image(output_path, fname, fsize, content_type)
                        print(f"   -> [OK] Uploaded, asset_id: {asset_id}")
                        
                        # Use image_name (the raw src from JSON) so the regex matches perfectly!
                        replacement_map[image_name] = asset_id
                    except Exception as e:
                        print(f"   -> [ERROR] Upload failed for {fname}: {e}")

    return replacement_map

def main():
    signal.signal(signal.SIGINT, signal_handler)
    print("Starting Data Migration Pipeline (One-Go Sequence)...")
    
    grouped_output = defaultdict(list)
    new_url_data_output = defaultdict(lambda: defaultdict(list))
    
    # --- SMART RESUME: Pre-load existing JSON outputs ---
    if os.path.exists(OUTPUT_DIR):
        for f in os.listdir(OUTPUT_DIR):
            if f.endswith(".json"):
                stype = f.replace(".json", "")
                try:
                    with open(os.path.join(OUTPUT_DIR, f), "r", encoding="utf-8") as fp:
                        grouped_output[stype] = json.load(fp)
                except Exception: pass

    NEW_URL_DATA_BASE_DIR = r"C:\Users\trupa\OneDrive\Desktop\Alef\migration\core_data _with_transformed_image"
    if os.path.exists(NEW_URL_DATA_BASE_DIR):
        for BASE_DIR, _, files in os.walk(NEW_URL_DATA_BASE_DIR):
            cat = os.path.basename(BASE_DIR)
            for f in files:
                if f.endswith(".json"):
                    stype = f.replace(f"{cat}_", "").replace(".json", "")
                    try:
                        with open(os.path.join(BASE_DIR, f), "r", encoding="utf-8") as fp:
                            new_url_data_output[cat][stype] = json.load(fp)
                    except Exception: pass
    # ----------------------------------------------------
    
    stage_records = {}
    if os.path.exists(STAGE_RECORD_FILE):
        try:
            with open(STAGE_RECORD_FILE, "r", encoding="utf-8") as f:
                stage_records = json.load(f)
        except json.JSONDecodeError:
            pass
            
    logger = DebugLogger(log_dir="logs/migration_filter_logs")
    
    total_processed = 0
    total_passed = 0
    total_filtered = 0
    
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    for root, dirs, files in os.walk(INPUT_DIR):
        category = os.path.basename(root)
        if shutdown_requested: break
            
        for file in files:
            if shutdown_requested: break
                
            if file.endswith(".json"):
                file_path = os.path.join(root, file)
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        
                    if not isinstance(data, list): continue
                        
                    for question in data:
                        if shutdown_requested: break
                            
                        qid = question.get("question_id")
                        if not qid: continue
                        
                        # Smart Resume Check
                        if qid in stage_records:
                            status = stage_records[qid].get("overall_status")
                            if status in ["filtered_out", "no_images_found", "success"]:
                                print(f"\n{qid}\nSkipped (already processed)")
                                if status == "filtered_out": total_filtered += 1
                                continue
                                
                        print(f"\n{qid}")
                        total_processed += 1
                        lesson = question.get("lesson")
                        question_type = None
                        response_data = question.get("response", {})
                        if isinstance(response_data, dict):
                            question_type = response_data.get("type") or response_data.get("metadata", {}).get("formatType")
                            
                        if qid and qid not in stage_records:
                            stage_records[qid] = {
                                "question_type": question_type,
                                "overall_status": "in_progress",
                                "stages": {}
                            }
                        
                        # passed_filter = filter_question(question)
                        now_str = datetime.now(timezone.utc).isoformat()
                        
                        # if passed_filter:
                        total_passed += 1
                        if qid:
                            stage_records[qid]["stages"]["stage_1_filter"] = {"status": "passed", "timestamp": now_str}
                        print("stage - 1 completed")
                        
                        res = process_next_stage(question, category)
                        if res:
                            q_imgs = res.get("question_images", [])
                            o_imgs = res.get("option_images", [])
                            a_imgs = res.get("image_audit", [])
                            has_images = bool(q_imgs or o_imgs or a_imgs)
                            source_type = res.get("source_type", "unknown")
                            
                            # Keep saving to OUTPUT_DIR for debugging/logs
                            grouped_output[source_type].append(res)
                            out_file_res = os.path.join(OUTPUT_DIR, f"{source_type}.json")
                            with open(out_file_res, "w", encoding="utf-8") as f:
                                json.dump(grouped_output[source_type], f, indent=2, ensure_ascii=False)
                            
                            if has_images:
                                print("stage - 2 completed (images found)")
                                
                                # Transform & Upload Images immediately
                                replacement_map = process_and_upload_images(res, category)
                                
                                # Replace URLs
                                q_str = json.dumps(question)
                                for short_name, asset_id in replacement_map.items():
                                    # Use greedy match to fully replace relative paths
                                    pattern = r'[a-zA-Z0-9_./-]*' + re.escape(short_name)
                                    q_str = re.sub(pattern, asset_id, q_str)
                                    
                                new_q = json.loads(q_str)
                                
                                # Save Final Output Immediately
                                cat_dir = os.path.join(NEW_URL_DATA_BASE_DIR, category)
                                os.makedirs(cat_dir, exist_ok=True)
                                out_file = os.path.join(cat_dir, f"{category}_{source_type}.json")
                                new_url_data_output[category][source_type].append(new_q)
                                with open(out_file, "w", encoding="utf-8") as f:
                                    json.dump(new_url_data_output[category][source_type], f, indent=2, ensure_ascii=False)
                                
                                if qid:
                                    stage_records[qid]["stages"]["stage_2_image_resolution"] = {"status": "passed", "timestamp": datetime.now(timezone.utc).isoformat()}
                                    stage_records[qid]["overall_status"] = "success"
                                    stage_records[qid]["source_type"] = source_type
                                    
                            else:
                                print("stage - 2 skipped (no images)")
                                
                                # Save Final Output Immediately
                                cat_dir = os.path.join(NEW_URL_DATA_BASE_DIR, category)
                                os.makedirs(cat_dir, exist_ok=True)
                                out_file = os.path.join(cat_dir, f"{category}_{source_type}.json")
                                new_url_data_output[category][source_type].append(question)
                                with open(out_file, "w", encoding="utf-8") as f:
                                    json.dump(new_url_data_output[category][source_type], f, indent=2, ensure_ascii=False)
                                    
                                if qid:
                                    stage_records[qid]["stages"]["stage_2_image_resolution"] = {"status": "skipped", "timestamp": datetime.now(timezone.utc).isoformat(), "reason": "No images"}
                                    stage_records[qid]["overall_status"] = "success"
                                    stage_records[qid]["source_type"] = source_type
                            
                        else:
                            if qid:
                                stage_records[qid]["stages"]["stage_2_image_resolution"] = {"status": "failed", "timestamp": datetime.now(timezone.utc).isoformat(), "reason": "Failed or skipped"}
                                stage_records[qid]["overall_status"] = "failed_at_stage_2"
                        # else:
                        #     total_filtered += 1
                        #     if qid:
                        #         stage_records[qid]["stages"]["stage_1_filter"] = {"status": "skipped", "timestamp": now_str, "reason": "Filtered out in Stage 1"}
                        #         stage_records[qid]["overall_status"] = "filtered_out"
                                
                        #     print("stage - 1 skipped (filtered out)")
                        #     logger.log(question_id=qid, lesson=lesson, question_type=question_type, reason="Filtered out in Stage 1", file_path=file_path)
                            
                except Exception as e:
                    print(f"Error reading or processing {file_path}: {e}")
                    
                with open(STAGE_RECORD_FILE, "w", encoding="utf-8") as f:
                    json.dump(stage_records, f, indent=2)

    print("\n--- Processing Complete ---")
    total_output_records = sum(len(items) for items in grouped_output.values())
    total_new_url_records = sum(len(items) for st in new_url_data_output.values() for items in st.values())

    print("----------------------------------")
    print("\n--- Migration Pipeline Summary ---")
    print(f"Total Questions Processed : {total_processed}")
    print(f"Total Passed to Next Stage: {total_passed}")
    print(f"Total Filtered Out        : {total_filtered}")
    print(f"Total With Images Output  : {total_output_records}")
    print(f"Total New URL Records     : {total_new_url_records}")
    print("----------------------------------")
    
if __name__ == "__main__":
    main()
