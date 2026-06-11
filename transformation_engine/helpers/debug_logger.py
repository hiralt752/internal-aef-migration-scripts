import json
import os
import csv
from datetime import datetime
from threading import Lock


class DebugLogger:

    def __init__(self, log_dir="logs"):
        self.log_dir = log_dir
        self.lock = Lock()

        os.makedirs(self.log_dir, exist_ok=True)

        self.json_log_file = os.path.join(self.log_dir, "debug_log.json")
        self.csv_log_file = os.path.join(self.log_dir, "debug_log.csv")

        # initialize files if not exist
        if not os.path.exists(self.json_log_file):
            with open(self.json_log_file, "w") as f:
                json.dump([], f)

        if not os.path.exists(self.csv_log_file):
            with open(self.csv_log_file, "w", newline="") as f:
                writer = csv.writer(f)
                writer.writerow([
                    "timestamp",
                    "question_id",
                    "lesson",
                    "question_type",
                    "reason",
                    "file_path"
                ])

    def log(self,
            question_id=None,
            lesson=None,
            question_type=None,
            reason=None,
            file_path=None):

        entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "question_id": question_id,
            "lesson": lesson,
            "question_type": question_type,
            "reason": reason,
            "file_path": file_path
        }

        with self.lock:

            with open(self.json_log_file, "r+") as f:

                try:
                    data = json.load(f)

                    if not isinstance(data, list):
                        data = []

                except Exception:
                    data = []

                data.append(entry)

                f.seek(0)
                json.dump(data, f, indent=2)
             

        # -------- CSV LOG --------
        with open(self.csv_log_file, "a", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                entry["timestamp"],
                question_id,
                lesson,
                question_type,
                reason,
                file_path
            ])

    def log_exception(self, wrapper, lesson, file_path, error):
        self.log(
            question_id=wrapper.get("question_id"),
            lesson=lesson,
            question_type=wrapper.get("response", {}).get("type"),
            reason=str(error),
            file_path=file_path
        )