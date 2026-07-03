import requests
import os
import json
from glob import glob
from dotenv import load_dotenv
from pprint import pprint
from pathlib import Path


load_dotenv()

key_list=["question_images", "option_images", "image_audit", "question_audios", "question_videos"]

media_path=r"C:\Users\PC\Desktop\alef_new\internal_repo\media_migration\image_transformation\image_transformation_output"
BASE_DIR = Path(__file__).resolve().parent.parent
upload_path=os.path.join(BASE_DIR,"image_upload")

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

def check_json_exists(upload_path, file_name, data):
    if os.path.exists(os.path.join(upload_path,file_name)):
        write_in_json(os.path.join(upload_path,file_name),data)
        
    else:
        os.makedirs(upload_path, exist_ok=True)
        create_json(os.path.join(upload_path,file_name))
        write_in_json(os.path.join(upload_path,file_name),data)

def create_json(file_path, data=[]):
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

def write_in_json(file_path, list_data):
    with open(file_path, "r", encoding='utf-8') as f:
        data=json.load(f)
        
    data.append(list_data)
    
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def migration_step_1(URL, image_data, question_id):

    final_url=f"{URL}/authoring-content-service/api/assets/presigned-upload-url?"

    # Resolve filename & extension dynamically, handling webp/jfif conversion to png
    src_basename = os.path.basename(image_data.get('src'))
    name_without_ext, ext = os.path.splitext(src_basename)
    ext = ext[1:].lower()
    content_type = image_data.get("content_type", "IMAGE")
    
    if content_type == "IMAGE" and ext in ("webp", "jfif"):
        src_basename = f"{name_without_ext}.png"
        ext = "png"

    # Search for the media locally using both custom path and local path fallback.
    local_path = os.path.join(BASE_DIR, "image_transformation", "image_transformation_output")
    image_path = []
    for path in (media_path, local_path):
        if os.path.exists(path):
            image_path = glob(
                os.path.join(path, "**", f"{question_id}_*_{src_basename}"),
                recursive=True
            )
            if image_path:
                break
    
    # Make a file name for server B
    file_name=f"{question_id}_{image_data.get("key")}_{src_basename}"

    if not image_path:
        print(f"Error: media file not found locally for question {question_id}, src {image_data.get('src')}")
        return {file_name: {"status_code": 404, "api_status": "failed", "response": "Local file not found"}}

    headers = {
        "X-tenantId": "shared",
        "Authorization": os.getenv("BEARER_TOKEN")
    }

    # Resolve dynamic MIME types
    if content_type == "AUDIO":
        mime_type = f"audio/{ext}"
        if ext == "mp3":
            mime_type = "audio/mpeg"
    elif content_type == "VIDEO":
        mime_type = f"video/{ext}"
    else:
        mime_type = f"image/{ext}"
        if ext == "jpg":
            mime_type = "image/jpeg"

    params = {
        "fileName":file_name,
        "contentType":mime_type,
        "fileSize":f"{os.path.getsize(image_path[0])}"
    }

    response = requests.get(final_url, headers=headers, params=params)
    
    # Making a custom response
    result={}
    temp_dict = {
        "api_status":"success" if response.status_code==200 else "failed",
        "status_code": response.status_code,
        "response": response.json()
    }
    result[file_name]=temp_dict

    # Storing the response in step_1_response.json
    check_json_exists(upload_path,"step_1_response.json",result)

    return result

def migration_step_2(step_1_response, image_data, URL, question_id):
    
    key=next(iter(step_1_response))
    
    if step_1_response[key].get("status_code") == 200 :
        
        # Resolve filename & extension dynamically, handling webp/jfif conversion to png
        src_basename = os.path.basename(image_data.get('src'))
        name_without_ext, ext = os.path.splitext(src_basename)
        ext = ext[1:].lower()
        content_type = image_data.get("content_type", "IMAGE")
        
        if content_type == "IMAGE" and ext in ("webp", "jfif"):
            src_basename = f"{name_without_ext}.png"
            ext = "png"

        # Search for the media locally using both custom path and local path fallback.
        local_path = os.path.join(BASE_DIR, "image_transformation", "image_transformation_output")
        image_path = []
        for path in (media_path, local_path):
            if os.path.exists(path):
                image_path = glob(
                    os.path.join(path, "**", f"{question_id}_*_{src_basename}"),
                    recursive=True
                )
                if image_path:
                    break
        
        if not image_path:
            return {key: {"status_code": 404, "api_status": "failed", "response": "Local file not found"}}

        file_name=f"{question_id}_{image_data.get("key")}_{src_basename}"

        # Getting resignedUrl from response of step 1 migration
        presigned_url=step_1_response[key].get("response").get("presignedUrl").get("url")

        # Resolve dynamic MIME types
        if content_type == "AUDIO":
            mime_type = f"audio/{ext}"
            if ext == "mp3":
                mime_type = "audio/mpeg"
        elif content_type == "VIDEO":
            mime_type = f"video/{ext}"
        else:
            mime_type = f"image/{ext}"
            if ext == "jpg":
                mime_type = "image/jpeg"

        headers = {
            "Origin":URL,
            "Referer":f"{URL}/",
            "x-ms-blob-type": "BlockBlob",
            "Content-Type": mime_type
        }

        with open(image_path[0], "rb") as f:
            response = requests.put(presigned_url, headers=headers, data=f)

        result={}
        temp_dict = {
            "api_status":"success" if response.status_code==201 else "failed",
            "status_code": response.status_code,
            "response": response.text
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
    
def migration_step_3(URL, step_1_response, question_code, media_count, question_id, image_data, step_2_response):
    
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

        response = requests.post(final_url, headers=headers, json=payload)

        result={}
        temp_dict = {
            "api_status":"success" if response.status_code==201 else "failed",
            "status_code": response.status_code,
            "response": response.json()
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
        return

    img_count = 1

    for key in key_list:
        if resolution_list.get(key):
            for image in resolution_list.get(key):
                question_id = resolution_list.get("question_id")

                step_1_response = migration_step_1(URL, image, question_id)
                
                step_2_response = migration_step_2(step_1_response, image, URL, question_id)
                
                step_3_response = migration_step_3(URL, step_1_response, question_code, img_count, question_id, image, step_2_response)

                question_data = url_replacement(step_3_response, step_1_response, question_data, image)

                content_type = image.get("content_type", "IMAGE").lower()
                print(f"\t{img_count} {content_type} migrated")
                img_count += 1

    # write ONCE, after ALL images (question_images, option_images, image_audit) are done
    path = os.path.join(BASE_DIR, "final_output", folder)
    check_json_exists(path, file_name, question_data)