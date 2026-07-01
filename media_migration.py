import os
import json
import time
from pprint import pprint
from image_resolution_engine.analyzers.dispatcher import analyze_question
from image_transformation.image_processor import process_resolution_output
from image_migration.migration import image_migration

# path = r"C:\Users\PC\Desktop\alef_new\test_script\test_data"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INPUT_FOLDER = os.path.join(BASE_DIR,"test_data")
IMAGE_RESOLUTION_OUTPUT = os.path.join(BASE_DIR,r"image_resolution_engine\image_resolution_output")
# print(INPUT_FOLDER)

folder_list=os.listdir(INPUT_FOLDER)

URL = "https://ccl-rc-az.nprd.alefed.com"  #DEV URL
# URL = "https://shared.alefed.com"        #PROD URL

def terminal_choice():
    choice = input("Continue execution? (y/n): ")
    
    if choice == "y":
        print("continue...")
    else:
        print("execution stoped")

def write_in_json(file_path, list_data):
    with open(file_path, "r", encoding='utf-8') as f:
        data=json.load(f)
        
    data.append(list_data)
    
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

def create_folder(file_path):
    os.makedirs(file_path, exist_ok=True)
    
def create_json(file_path, data=[]):
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)
    
create_folder(IMAGE_RESOLUTION_OUTPUT)
    
#loop for each subject
for folder in folder_list:  
    print(f"Processing Subject - {folder}")
    start_time = time.perf_counter()

    create_folder(os.path.join(IMAGE_RESOLUTION_OUTPUT,folder))
    
    #loop for each file
    for file in os.listdir(os.path.join(INPUT_FOLDER,folder)): 
        print(f"Processing file - {file}")
        create_json(os.path.join(IMAGE_RESOLUTION_OUTPUT,folder,file))
        
        #reading json file 
        with open(os.path.join(INPUT_FOLDER,folder,file), "r", encoding="utf-8") as f: 
            data=json.load(f)
            
            # Process one question at a time 
            for file_len in range(len(data)):
                question_id=data[file_len].get("question_id")
                question_type=data[file_len].get("response").get("type")
                question_code=data[file_len].get("response").get("code")

                print(f"\tProcessing question :- {question_id}")
                
                # getting resolution for image
                image_resolution=analyze_question(data[file_len], question_type, folder)
                write_in_json(os.path.join(IMAGE_RESOLUTION_OUTPUT,folder,file),image_resolution)
                print(f"\tgot the image resolution output")
                
                # Applying image transfoemation
                process_resolution_output(image_resolution)
                print("\tImage transformed ...")

                # Image migration
                image_migration(URL, image_resolution, question_code)
                # terminal_choice()
                
                print("\tNext question ...\n")
            
        print(f"All question of {file} is processed ...")
    
    print(f"{folder} folder processed ...\n")
    end_time = time.perf_counter()
    print(f"Execution time: {end_time - start_time:.2f} seconds")

        
