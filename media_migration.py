import os
import json
import time
import signal
from image_resolution_engine.analyzers.dispatcher import analyze_question
from image_transformation.image_processor import process_resolution_output
from image_migration.migration import image_migration

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INPUT_FOLDER = os.path.join(BASE_DIR, "test_data")
IMAGE_RESOLUTION_OUTPUT = os.path.join(
    BASE_DIR,
    "image_resolution_engine",
    "image_resolution_output"
)

URL = "https://ccl-rc-az.nprd.alefed.com"  # DEV URL
# URL = "https://shared.alefed.com" #PROD URL

stop_requested = False


def handle_sigint(signum, frame):
    global stop_requested
    print("\nCtrl+C detected. Finishing current question, then stopping...")
    stop_requested = True


signal.signal(signal.SIGINT, handle_sigint)


def write_in_json(file_path, item):
    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    data.append(item)

    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def create_folder(path):
    os.makedirs(path, exist_ok=True)


def create_json(file_path, data=None):
    if data is None:
        data = []

    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# Create tracking file
question_processed_file = os.path.join(BASE_DIR, "question_processed.json")
create_json(question_processed_file)

# Create output folder
create_folder(IMAGE_RESOLUTION_OUTPUT)

start_time = time.perf_counter()

for folder in os.listdir(INPUT_FOLDER):
    print(f"Processing Subject - {folder}")

    subject_output = os.path.join(IMAGE_RESOLUTION_OUTPUT, folder)
    create_folder(subject_output)

    input_folder = os.path.join(INPUT_FOLDER, folder)

    for file in os.listdir(input_folder):

        print(f"Processing file - {file}")

        resolution_output_file = os.path.join(subject_output, file)
        create_json(resolution_output_file)

        input_file = os.path.join(input_folder, file)

        with open(input_file, "r", encoding="utf-8") as f:
            questions = json.load(f)

        question_count = 1

        for question in questions:

            if stop_requested:
                print("Stop flag set. Exiting before next question.")
                break

            question_id = question["question_id"]
            question_type = question["response"]["type"]
            question_code = question["response"]["code"]

            print(f"\t[{question_count}/{len(questions)}] Processing question :- {question_id}")

            # Step 1 - Analyze
            image_resolution = analyze_question(
                question,
                question_type,
                folder
            )

            write_in_json(resolution_output_file, image_resolution)

            print("\tgot the image resolution output")

            # Step 2 - Transform
            process_resolution_output(image_resolution)

            # Step 3 - Upload
            image_migration(
                URL,
                image_resolution,
                question_code,
                question,
                file,
                folder
            )

            # Track processed question
            write_in_json(question_processed_file, question_id)

            print("\tNext question ...\n")

            question_count += 1

        print(f"All questions of {file} are processed ...")

    print(f"{folder} folder processed ...\n")

end_time = time.perf_counter()

print(f"Execution time: {end_time - start_time:.2f} seconds")