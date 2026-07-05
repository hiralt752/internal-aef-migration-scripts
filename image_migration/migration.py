import requests
import os
import json
from glob import glob
from dotenv import load_dotenv
from pprint import pprint
from pathlib import Path


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
    if os.path.exists(os.path.join(upload_path,file_name)):
        write_in_json(os.path.join(upload_path,file_name),data)

    else:
        os.makedirs(upload_path, exist_ok=True)
        create_json(os.path.join(upload_path,file_name))
        write_in_json(os.path.join(upload_path,file_name),data)

def create_json(file_path, data=None):
    if data is None:
        data = []
    _atomic_write_json(file_path, data, indent=4)

def write_in_json(file_path, list_data):
    with open(file_path, "r", encoding='utf-8') as f:
        data=json.load(f)

    data.append(list_data)

    _atomic_write_json(file_path, data)


def append_ignored_question(question_id: str, reason: str) -> None:
    """ignored_question.json is a dict of {question_id: reason} for any question
    media_migration.py gives up on (missing local media, malformed record, etc.)."""
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

    matches = glob(
        os.path.join(media_path, "**", f"{question_id}_*_{os.path.basename(src)}"),
        recursive=True,
    )
    return matches[0] if matches else None


def migration_step_1(URL, image_data, question_id, content_type, local_path):

    final_url=f"{URL}/authoring-content-service/api/assets/presigned-upload-url?"

    # Make a file name for server B
    file_name=f"{question_id}_{image_data.get("key")}_{os.path.basename(image_data.get("src"))}"

    headers = {
        "X-tenantId": "shared",
        "Authorization": os.getenv("BEARER_TOKEN")
    }

    params = {
        "fileName":file_name,
        "contentType":f"{content_type.lower()}/{os.path.splitext(os.path.basename(image_data.get("src")))[1][1:]}",
        "fileSize":f"{os.path.getsize(local_path)}"
    }

    # pprint(f"step -1 {params}\n")

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

    key=next(iter(step_1_response))

    if step_1_response[key].get("status_code") == 200 :

        file_name=f"{question_id}_{image_data.get("key")}_{os.path.basename(image_data.get("src"))}"

        result={}
        try:
            # Getting presignedUrl from response of step 1 migration
            presigned_url=step_1_response[key].get("response").get("presignedUrl").get("url")

            headers = {
                "Origin":URL,
                "Referer":f"{URL}/",
                "x-ms-blob-type": "BlockBlob",
                "Content-Type": f"{content_type.lower()}/{os.path.splitext(os.path.basename(image_data.get("src")))[1][1:]}"
            }

            # pprint(f"step -2 {headers}\n")

            with open(local_path, "rb") as f:
                response = requests.put(presigned_url, headers=headers, data=f, timeout=REQUEST_TIMEOUT)

            temp_dict = {
                "api_status":"success" if response.status_code==201 else "failed",
                "status_code": response.status_code,
                "response": response.text
            }
        except requests.exceptions.RequestException as error:
            print(f"\tstep 2 failed - network/API error for {file_name}: {error}")
            temp_dict = {
                "api_status": "failed",
                "status_code": "REQUEST_ERROR",
                "response": str(error),
            }
        except (AttributeError, OSError) as error:
            print(f"\tstep 2 failed - could not read presigned URL / local file for {file_name}: {error}")
            temp_dict = {
                "api_status": "failed",
                "status_code": "LOCAL_ERROR",
                "response": str(error),
            }

        result[file_name]=temp_dict
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

        # key=next(iter(response))
        file_name=f"{question_id}_{image_data.get("key")}_{os.path.basename(image_data.get("src"))}"

        final_url = f"{URL}/authoring-content-service/api/assets/create-and-publish"

        headers = {
            "X-tenantId": "shared",
            "Authorization": os.getenv("BEARER_TOKEN"),
            "Content-Type": "application/json"
        }

        if content_type == "IMAGE" :
            prefix= "img"
        elif content_type == "AUDIO" :
            prefix= "aud"
        else :
            prefix= "vid"

        payload={
            "fileName":key,
            "fileId": step_1_response[key].get("response").get("fileId"),
            "uploadId": step_1_response[key].get("response").get("uploadId"),
            "title": f"{question_code}_{prefix}_{media_count}",
            "description": f"{question_code}_{prefix}_{media_count}",
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
    """Upload every image/audio/video described in resolution_list.

    Returns (media_migrated_count, ignored) where:
    - media_migrated_count: number of media items successfully published this call.
    - ignored: True if the question was abandoned because its locally-transformed
      media could not be found on disk (logged to ignored_question.json), in which
      case final_output is NOT written for this question.
    """
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
                    return media_migrated_count, True

                step_1_response = migration_step_1(URL, image, question_id, content_type, local_path)

                step_2_response = migration_step_2(step_1_response, image, URL, question_id, content_type, local_path)

                step_3_response = migration_step_3(URL, step_1_response, question_code, img_count, question_id, image, step_2_response, content_type)

                question_data = url_replacement(step_3_response, step_1_response, question_data, image)

                step_3_key = next(iter(step_3_response))
                if step_3_response[step_3_key].get("status_code") == 201:
                    media_migrated_count += 1

                print(f"\t{img_count} image migrated")
                img_count += 1


    # write ONCE, after ALL images (question_images, option_images, image_audit) are done
    path = os.path.join(BASE_DIR, "final_output", folder)
    check_json_exists(path, file_name, question_data)

    return media_migrated_count, False
