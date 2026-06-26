import os
import json
from pathlib import Path

from dotenv import load_dotenv
from google import genai

load_dotenv()

client = genai.Client(
    api_key=os.getenv("GEMINI_API_KEY")
)

CURRICULUM_DIR = Path("curriculum")
CACHE_FILE = Path("cache/uploaded_files.json")

uploaded_files = {}

for csv_file in CURRICULUM_DIR.rglob("*.csv"):

    subject = csv_file.parent.name.lower()

    print(f"Uploading: {csv_file}")

    uploaded = client.files.upload(
        file=str(csv_file)
    )

    key = csv_file.stem.lower()

    uploaded_files[key] = {
        "subject": subject,
        "file_name": csv_file.name,
        "file_path": str(csv_file),
        "gemini_file_name": uploaded.name
    }

    print(
        f"Uploaded {csv_file.name} "
        f"-> {uploaded.name}"
    )

CACHE_FILE.parent.mkdir(exist_ok=True)

with open(CACHE_FILE, "w", encoding="utf-8") as f:
    json.dump(
        uploaded_files,
        f,
        indent=2,
        ensure_ascii=False
    )

print("\nUpload Completed")