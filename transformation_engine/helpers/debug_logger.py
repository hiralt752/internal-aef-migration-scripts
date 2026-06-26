import json
import os
import csv
from datetime import datetime
from threading import Lock


class DebugLogger:
    _lock = Lock()

    def __init__(self, log_dir="logs"):
        self.log_dir = log_dir

        os.makedirs(self.log_dir, exist_ok=True)

        # Use JSONL so each write is append-only instead of rewriting a growing array.
        self.json_log_file = os.path.join(self.log_dir, "debug_log.jsonl")
        self.csv_log_file = os.path.join(self.log_dir, "debug_log.csv")

        # initialize files if not exist
        if not os.path.exists(self.json_log_file):
            with open(self.json_log_file, "w", encoding="utf-8") as f:
                f.write("")

        if not os.path.exists(self.csv_log_file):
            with open(self.csv_log_file, "w", newline="", encoding="utf-8") as f:
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

        with self._lock:
            with open(self.json_log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")

            with open(self.csv_log_file, "a", newline="", encoding="utf-8") as f:
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