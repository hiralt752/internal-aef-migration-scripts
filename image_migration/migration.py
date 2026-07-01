import requests
import os
import json
from glob import glob
from dotenv import load_dotenv
from pprint import pprint
from pathlib import Path


load_dotenv()

key_list=["question_images", "option_images", "image_audit"]

media_path=r"C:\Users\PC\Documents\project_migration\media"
BASE_DIR = Path(__file__).resolve().parent.parent
upload_path=os.path.join(BASE_DIR,"image_upload")

def check_json_exists(upload_path, file_name, data):
    if os.path.exists(os.path.join(upload_path,file_name)):
        write_in_json(os.path.join(upload_path,file_name),data)
        
    else:
        os.makedirs(upload_path, exist_ok=True)
        create_json(os.path.join(upload_path,file_name))
        write_in_json(os.path.join(upload_path,file_name),data)

def create_json(file_path, data=[]):
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)

def write_in_json(file_path, list_data):
    with open(file_path, "r", encoding='utf-8') as f:
        data=json.load(f)
        
    data.append(list_data)
    
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

def migration_step_1(URL, image_data, question_id):

    final_url=f"{URL}/authoring-content-service/api/assets/presigned-upload-url?"

    # Search for the image locally using the custom path. Returns [] if not found. 
    image_path=glob(
        os.path.join(media_path,"**",f"{question_id}_*_{os.path.basename(image_data.get('src'))}"),
        recursive=True
        )
    
    # Make a file name for server B
    file_name=f"{question_id}_{image_data.get("key")}_{os.path.basename(image_data.get("src"))}"

    headers = {
        "X-tenantId": "shared",
        "Authorization": os.getenv("BEARER_TOKEN")
    }

    params = {
        "fileName":file_name,
        "contentType":f"image/{os.path.splitext(os.path.basename(image_data.get("src")))[1][1:]}",
        "fileSize":f"{os.path.getsize(image_path[0])}"
    }

    response = requests.get(final_url, headers=headers, params=params)
    
    # Making a custom response
    result={}
    temp_dict = {
    "status_code": response.status_code,
    "response": response.json()
    }
    result[file_name]=temp_dict

    # Storing the response in step_1_response.json
    check_json_exists(upload_path,"step_1_response.json",result)

    return result

def migration_step_2(response, image_data, URL, question_id):

    image_path=glob(
        os.path.join(media_path,"**",f"{question_id}_*_{os.path.basename(image_data.get('src'))}"),
        recursive=True
        )
    file_name=f"{question_id}_{image_data.get("key")}_{os.path.basename(image_data.get("src"))}"

    # Getting resignedUrl from response of step 1 migration
    key=next(iter(response))
    presigned_url=response[key].get("response").get("presignedUrl").get("url")

    headers = {
        "Origin":URL,
        "Referer":f"{URL}/",
        "x-ms-blob-type": "BlockBlob",
        "Content-Type": f"image/{os.path.splitext(os.path.basename(image_data.get("src")))[1][1:]}"
    }

    with open(image_path[0], "rb") as f:
        response = requests.put(presigned_url, headers=headers, data=f)

    result={}
    temp_dict = {
    "status_code": response.status_code,
    "response": response.text
    }
    result[file_name]=temp_dict
    check_json_exists(upload_path,"step_2_response.json",result)
    
def migration_step_3(URL, response, question_code, media_count, question_id, image_data):

    key=next(iter(response))
    file_name=f"{question_id}_{image_data.get("key")}_{os.path.basename(image_data.get("src"))}"

    final_url = f"{URL}/authoring-content-service/api/assets/create-and-publish"

    headers = {
        "X-tenantId": "shared",
        "Authorization": os.getenv("BEARER_TOKEN"),
        "Content-Type": "application/json"
    }
    
    payload={
        "fileName":key,
        "fileId": response[key].get("response").get("fileId"),
        "uploadId": response[key].get("response").get("uploadId"),
        "title": f"{question_code}_img_{media_count}",
        "description": f"{question_code}_img_{media_count}",
        "type": "IMAGE",
        "metadata": [],
        "systemMetadata": [],
        "tagIds": [],
    }

    response = requests.post(final_url, headers=headers, json=payload)

    result={}
    temp_dict = {
    "status_code": response.status_code,
    "response": response.json()
    }
    result[file_name]=temp_dict
    check_json_exists(upload_path,"step_3_response.json",result)


def image_migration(URL, resolution_list, question_code):

    img_count=1

    # Loop through key_list ("question_images", "option_images", "image_audit")
    for key in key_list:

        # if True means the list is not empty there are image to process
        if resolution_list.get(key) :

            # Loop inside key for each image
            for image in resolution_list.get(key):
                # pprint(image)
                iamge_url = image.get("src")
                # print(iamge_url)
                question_id=resolution_list.get("question_id")

                step_1_response=migration_step_1(URL, image, question_id)
                    
                migration_step_2(step_1_response, image, URL, question_id)
                    
                migration_step_3(URL, step_1_response, question_code, img_count, question_id, image)

                print(f"\t{img_count} image migrated")

                img_count=img_count+1
