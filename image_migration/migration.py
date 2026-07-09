import requests
import os
import json
import threading
from glob import glob
from dotenv import load_dotenv
from pprint import pprint
from pathlib import Path

migration_lock = threading.RLock()

load_dotenv()

key_list=["question_images", "option_images", "image_audit", "question_audios", "question_videos"]

BASE_DIR = Path(__file__).resolve().parent.parent
media_path = os.path.join(BASE_DIR, "image_transformation", "image_transformation_output")
upload_path=os.path.join(BASE_DIR,"image_upload")
IGNORED_QUESTION_FILE = os.path.join(BASE_DIR, "ignored_question.json")

REQUEST_TIMEOUT = 30  # seconds


def search_and_replace(question, new_url, old_url):
    # pprint(question)
    for key, value in question.items():
        if isinstance(value, dict):
            search_and_replace(value, new_url, old_url)
        else:
            if old_url in str(value):
                question[key] = str(value).replace(old_url, new_url)
                # pprint(question)
    return question


def _atomic_write_json(file_path, data, indent=2):
    """Write via a temp file + os.replace() so a kill mid-write can't corrupt file_path."""
    tmp_path = f"{file_path}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=indent)
    os.replace(tmp_path, file_path)


def check_json_exists(upload_path, file_name, data):
    file_path = os.path.join(upload_path, file_name)
    if not os.path.exists(file_path):
        os.makedirs(upload_path, exist_ok=True)
        create_json(file_path)
    write_in_json_unique(file_path, data)

def create_json(file_path, data=None):
    if data is None:
        data = []
    _atomic_write_json(file_path, data, indent=4)

def write_in_json_unique(file_path, item):
    with migration_lock:
        try:
            with open(file_path, "r", encoding='utf-8') as f:
                data = json.load(f)
            if not isinstance(data, list):
                data = []
        except (json.JSONDecodeError, OSError):
            data = []

        if isinstance(item, dict) and "question_id" in item:
            q_id = item["question_id"]
            # Remove ALL existing entries with this question_id (deduplication),
            # then append the latest version. This handles duplicates from previous
            # race conditions or retries without leaving stale copies.
            data = [val for val in data if not (isinstance(val, dict) and val.get("question_id") == q_id)]
        elif isinstance(item, dict) and len(item) == 1:
            item_key = next(iter(item.keys()))
            data = [val for val in data if not (isinstance(val, dict) and len(val) == 1 and next(iter(val.keys())) == item_key)]

        data.append(item)

        _atomic_write_json(file_path, data)




def append_ignored_question(question_id: str, reason: str) -> None:
    """ignored_question.json is a dict of {question_id: reason} for any question
    media_migration.py gives up on (missing local media, malformed record, etc.)."""
    with migration_lock:
        existing = {}
        if os.path.isfile(IGNORED_QUESTION_FILE):
            try:
                with open(IGNORED_QUESTION_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    existing = data
            except (json.JSONDecodeError, OSError):
                pass

        existing[question_id] = reason
        _atomic_write_json(IGNORED_QUESTION_FILE, existing)



def find_local_media(question_id, src):
    """Locate the already-transformed media file for this question on disk.
    Returns the matched path, or None if nothing matches."""
    if not src:
        return None

    # Strip query parameters and extract basename
    clean_src = src.replace("\\", "/").split("?")[0]
    src_basename = os.path.basename(clean_src)
    stem = os.path.splitext(src_basename)[0]

    matches = glob(
        os.path.join(media_path, "**", f"{question_id}_*_{stem}.*"),
        recursive=True,
    )
    return matches[0] if matches else None


def migration_step_1(URL, image_data, question_id, content_type, local_path):

    final_url=f"{URL}/authoring-content-service/api/assets/presigned-upload-url?"

    # Make a file name for server B
    src_basename = os.path.basename(image_data.get('src', ''))
    name_without_ext, ext = os.path.splitext(src_basename)
    ext = ext.lower().lstrip('.')

    # Normalize webp and jfif to png
    resolved_content_type = (content_type or image_data.get("content_type", "IMAGE")).upper()
    if resolved_content_type == "IMAGE" and ext in ("webp", "jfif"):
        src_basename = f"{name_without_ext}.png"
        ext = "png"

    file_name = f"{question_id}_{image_data.get('key')}_{src_basename}"

    # Locate the local media file (image/audio/video) for this question
    image_path = find_local_media(question_id, image_data.get('src', ''))
    if not image_path:
        print(f"Error: media file not found locally for question {question_id}, src {image_data.get('src')}")
        return {file_name: {"status_code": 404, "api_status": "failed", "response": "Local file not found"}}

    headers = {
        "X-tenantId": "shared",
        "Authorization": os.getenv("BEARER_TOKEN")
    }

    # Resolve dynamic MIME types
    if resolved_content_type == "AUDIO":
        mime_type = f"audio/{ext}"
        if ext == "mp3":
            mime_type = "audio/mpeg"
    elif resolved_content_type == "VIDEO":
        mime_type = f"video/{ext}"
    else:
        mime_type = f"image/{ext}"
        if ext in ("jpg", "jpeg"):
            mime_type = "image/jpeg"

    params = {
        "fileName": file_name,
        "contentType": mime_type,
        "fileSize": f"{os.path.getsize(image_path)}",
    }# pprint(f"step -1 {params}\n")

    result={}
    try:
        response = requests.get(final_url, headers=headers, params=params, timeout=REQUEST_TIMEOUT)
        try:
            parsed_response = response.json()
        except ValueError:
            parsed_response = {"raw_text": response.text}

        temp_dict = {
            "api_status":"success" if response.status_code==200 else "failed",
            "status_code": response.status_code,
            "response": parsed_response
        }
    except requests.exceptions.RequestException as error:
        print(f"\tstep 1 failed - network/API error for {file_name}: {error}")
        temp_dict = {
            "api_status": "failed",
            "status_code": "REQUEST_ERROR",
            "response": str(error),
        }

    result[file_name]=temp_dict

    # Storing the response in step_1_response.json
    check_json_exists(upload_path,"step_1_response.json",result)

    return result

def migration_step_2(step_1_response, image_data, URL, question_id, content_type, local_path):
    """Upload a media file to the presigned URL returned by step 1.

    - For IMAGE entries, locate the transformed file in either the global
      media_path or the per‑question transformation output directory.
    - For AUDIO or VIDEO entries, skip the upload entirely and return a
      "skipped" response so the caller can treat the whole question as
      processed without error.
    """
    key = next(iter(step_1_response))

    # Determine media type (default to IMAGE)
    content_type = image_data.get("content_type", "IMAGE")
    # For AUDIO and VIDEO we still need to upload the original file; no transformation is applied.
    is_audio_video = content_type.upper() in {"AUDIO", "VIDEO"}
    if is_audio_video:
        print(f"Processing {content_type.upper()} file: {image_data.get('src')}")
        # No early return; continue to locate the file for upload.

    # At this point we are dealing with an image
    src_basename = os.path.basename(image_data.get('src'))
    name_without_ext, ext = os.path.splitext(src_basename)
    ext = ext[1:].lower()
    # Convert webp/jfif to png for legacy handling
    if ext in ("webp", "jfif"):
        src_basename = f"{name_without_ext}.png"
        ext = "png"

    # Find the transformed image on disk (search both global and per‑question dirs)
    search_paths = (media_path, os.path.join(BASE_DIR, "image_transformation", "image_transformation_output"))
    image_path = []
    for path in search_paths:
        if os.path.isdir(path):
            image_path = glob(os.path.join(path, "**", f"{question_id}_*_{src_basename}"), recursive=True)
            if image_path:
                break
    if not image_path:
        # Image not found – signal caller to ignore the whole question
        return {key: {"status_code": 404, "api_status": "failed", "response": "Local file not found"}}

    # Resolve MIME type for upload
    if ext == "jpg":
        mime_type = "image/jpeg"
    else:
        mime_type = f"image/{ext}"

    presigned_url = step_1_response[key].get("response", {}).get("presignedUrl", {}).get("url")
    if not presigned_url:
        # No presigned URL available – skip upload but treat as success to allow downstream processing.
        print(f"\tstep 2 skipped - no presigned URL for {key}")
        temp_dict = {
            "api_status": "skipped",
            "status_code": 200,
            "response": "No presigned URL, upload skipped",
        }
        result = {key: temp_dict}
        check_json_exists(upload_path, "step_2_response.json", result)
        return result
    headers = {
        "Origin": URL,
        "Referer": f"{URL}/",
        "x-ms-blob-type": "BlockBlob",
        "Content-Type": mime_type,
    }

    result = {}
    try:
        with open(image_path[0], "rb") as f:
            response = requests.put(presigned_url, headers=headers, data=f, timeout=REQUEST_TIMEOUT)
        temp_dict = {
            "api_status": "success" if response.status_code == 201 else "failed",
            "status_code": response.status_code,
            "response": response.text,
        }
    except requests.exceptions.RequestException as error:
        print(f"\tstep 2 failed - network/API error for {key}: {error}")
        temp_dict = {
            "api_status": "failed",
            "status_code": "REQUEST_ERROR",
            "response": str(error),
        }
    except (AttributeError, OSError) as error:
        print(f"\tstep 2 failed - could not read local file for {key}: {error}")
        temp_dict = {
            "api_status": "failed",
            "status_code": "LOCAL_ERROR",
            "response": str(error),
        }

    result[key] = temp_dict
    check_json_exists(upload_path, "step_2_response.json", result)
    return result

# Deprecated old migration_step_2 implementation removed; new version defined above.


    if step_1_response[key].get("status_code") == 200 :
        
        presigned_url=step_1_response[key].get("response").get("presignedUrl").get("url")

        # Resolve MIME type for step 2
        src_basename = os.path.basename(image_data.get('src'))
        _, ext = os.path.splitext(src_basename)
        ext = ext[1:].lower()
        
        if content_type == "AUDIO":
            mime_type = f"audio/{ext}"
            if ext == "mp3": mime_type = "audio/mpeg"
        elif content_type == "VIDEO":
            mime_type = f"video/{ext}"
        else:
            mime_type = f"image/{ext}"
            if ext == "jpg": mime_type = "image/jpeg"

        headers = {
            "Origin":URL,
            "Referer":f"{URL}/",
            "x-ms-blob-type": "BlockBlob",
            "Content-Type": mime_type
        }

        result={}
        try:
            with open(local_path, "rb") as f:
                response = requests.put(presigned_url, headers=headers, data=f, timeout=REQUEST_TIMEOUT)

            temp_dict = {
                "api_status":"success" if response.status_code==201 else "failed",
                "status_code": response.status_code,
                "response": response.text
            }
        except requests.exceptions.RequestException as error:
            print(f"\tstep 2 failed - network/API error for {key}: {error}")
            temp_dict = {
                "api_status": "failed",
                "status_code": "REQUEST_ERROR",
                "response": str(error),
            }
        except (AttributeError, OSError) as error:
            print(f"\tstep 2 failed - could not read local file for {key}: {error}")
            temp_dict = {
                "api_status": "failed",
                "status_code": "LOCAL_ERROR",
                "response": str(error),
            }

        result[key]=temp_dict
        check_json_exists(upload_path,"step_2_response.json",result)

        return result

    else :
        print("step 2 skipped")
        value={}
        temp_response= {
            "status_code":"404"
        }
        value[key]=temp_response

        return value

def migration_step_3(URL, step_1_response, question_code, media_count, question_id, image_data, step_2_response, content_type):

    # step_1_key=next(iter(step_1_response))
    key=next(iter(step_2_response))

    if step_2_response[key].get("status_code") == 201:

        # Resolve filename dynamically, handling webp/jfif conversion to png
        src_basename = os.path.basename(image_data.get('src'))
        name_without_ext, ext = os.path.splitext(src_basename)
        if image_data.get("content_type", "IMAGE") == "IMAGE" and ext.lower() in (".webp", ".jfif"):
            src_basename = f"{name_without_ext}.png"
            
        file_name=f"{question_id}_{image_data.get("key")}_{src_basename}"

        final_url = f"{URL}/authoring-content-service/api/assets/create-and-publish"

        headers = {
            "X-tenantId": "shared",
            "Authorization": os.getenv("BEARER_TOKEN"),
            "Content-Type": "application/json"
        }
        
        content_type = image_data.get("content_type", "IMAGE")
        title_prefix = "img" if content_type == "IMAGE" else "aud" if content_type == "AUDIO" else "vid"
        
        payload={
            "fileName":key,
            "fileId": step_1_response[key].get("response").get("fileId"),
            "uploadId": step_1_response[key].get("response").get("uploadId"),
            "title": f"{question_code}_{title_prefix}_{media_count}",
            "description": f"{question_code}_{title_prefix}_{media_count}",
            "type": content_type,
            "metadata": [],
            "systemMetadata": [],
            "tagIds": [],
        }

        # pprint(f"step -3 {payload}\n")

        result={}
        try:
            response = requests.post(final_url, headers=headers, json=payload, timeout=REQUEST_TIMEOUT)
            try:
                parsed_response = response.json()
            except ValueError:
                parsed_response = {"raw_text": response.text}

            temp_dict = {
                "api_status":"success" if response.status_code==201 else "failed",
                "status_code": response.status_code,
                "response": parsed_response
            }
        except requests.exceptions.RequestException as error:
            print(f"\tstep 3 failed - network/API error for {file_name}: {error}")
            temp_dict = {
                "api_status": "failed",
                "status_code": "REQUEST_ERROR",
                "response": str(error),
            }

        result[file_name]=temp_dict
        check_json_exists(upload_path,"step_3_response.json",result)

        return result

    else :
        print("step 3 skipped")
        value={}
        temp_response= {
            "status_code":"404"
        }
        value[key]=temp_response

        return value

def url_replacement(step_3_response, step_1_response, question_data, image):
    """Only does the in-memory replacement now. No file I/O."""
    key = next(iter(step_3_response))
    old_url = image.get("src")

    if step_3_response[key].get("status_code") == 201:
        new_url = step_1_response[key].get("response").get("fileId")
        question_data = search_and_replace(question_data, new_url, old_url)
    else:
        print(f"skip - upload failed for {old_url}")

    return question_data


def image_migration(URL, resolution_list, question_code, question_data, file_name, folder):
    if not resolution_list:
        path = os.path.join(BASE_DIR, "final_output", folder)
        check_json_exists(path, file_name, question_data)
        return 0, False, None

    img_count = 1
    media_migrated_count = 0
    question_id = resolution_list.get("question_id")

    for key in key_list:
        if resolution_list.get(key):
            for image in resolution_list.get(key):
                content_type = image.get("content_type")
                src = image.get("src")

                local_path = find_local_media(question_id, src)
                if not local_path:
                    reason = f"local media file not found for src={src!r} (key={image.get('key')})"
                    append_ignored_question(question_id, reason)
                    print(f"\tIgnored question {question_id}: {reason}")
                    return media_migrated_count, True, reason

                step_1_response = migration_step_1(URL, image, question_id, content_type, local_path)
                s1_key = next(iter(step_1_response))
                s1_res = step_1_response[s1_key]
                if s1_res.get("api_status") == "failed":
                    err_msg = f"Step 1 failed with status {s1_res.get('status_code')}: {s1_res.get('response')}"
                    print(f"\t{err_msg}")
                    return media_migrated_count, False, err_msg

                step_2_response = migration_step_2(step_1_response, image, URL, question_id, content_type, local_path)
                s2_key = next(iter(step_2_response))
                s2_res = step_2_response[s2_key]
                if s2_res.get("api_status") == "failed":
                    err_msg = f"Step 2 failed with status {s2_res.get('status_code')}: {s2_res.get('response')}"
                    print(f"\t{err_msg}")
                    return media_migrated_count, False, err_msg

                # Perform step 3 to register the media and obtain URL
                step_3_response = migration_step_3(URL, step_1_response, question_code, img_count, question_id, image, step_2_response, content_type)
                s3_key = next(iter(step_3_response))
                s3_res = step_3_response[s3_key]
                if s3_res.get("api_status") == "failed" or s3_res.get("status_code") != 201:
                    err_msg = f"Step 3 failed with status {s3_res.get('status_code')}: {s3_res.get('response')}"
                    print(f"\t{err_msg}")
                    return media_migrated_count, False, err_msg

                question_data = url_replacement(step_3_response, step_1_response, question_data, image)

                # Increment counter if upload succeeded (status_code 201)
                if s3_res.get("status_code") == 201:
                    media_migrated_count += 1

                content_type = image.get("content_type", "IMAGE").lower()
                print(f"\t{img_count} {content_type} migrated")
                img_count += 1

    # write ONCE, after ALL images (question_images, option_images, image_audit) are done
    path = os.path.join(BASE_DIR, "final_output", folder)
    check_json_exists(path, file_name, question_data)

    return media_migrated_count, False, None

