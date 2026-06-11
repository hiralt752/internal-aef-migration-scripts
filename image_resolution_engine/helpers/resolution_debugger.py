import json
import os
import orjson

def _get_base_dir():
    return os.path.join(os.getcwd(), "debug_logs")


def _get_log_file(question_type, event_type):

    base_dir = _get_base_dir()

    safe_qtype = (question_type or "UNKNOWN").upper()
    safe_event = (event_type or "UNKNOWN").upper()

    folder_path = os.path.join(base_dir, safe_qtype)
    os.makedirs(folder_path, exist_ok=True)

    return os.path.join(folder_path, f"{safe_event}.json")

def log_event(question_type, event_type, event):

    file_path = _get_log_file(question_type, event_type)

    existing = []
    if os.path.exists(file_path):
        try:
            with open(file_path, "rb") as f:
                existing = orjson.loads(f.read())
        except (json.JSONDecodeError, OSError):
            existing = []

    existing.append(event)

    with open(file_path, "wb") as f:
        f.write(orjson.dumps(existing, option=orjson.OPT_INDENT_2))

def log_skip(question_id, stage, reason, question_type=None,
             lesson=None, extra=None):

    event = {
        "type": "SKIP",
        "question_id": question_id,
        "stage": stage,
        "reason": reason,
        "extra": extra,
        "question_type": question_type,
        "lesson": lesson 
    }

    log_event(question_type, "SKIP", event)

def log_success(question_id, widget_type, resolution,
                question_type=None, lesson=None):

    event = {
        "type": "SUCCESS",
        "question_id": question_id,
        "widget_type": widget_type,
        "resolution": resolution,
        "question_type": question_type,
        "lesson": lesson
    }

    log_event(question_type, "SUCCESS", event)

def log_error(question_id, reason, question_type=None, extra=None):

    event = {
        "type": "ERROR",
        "question_id": question_id,
        "reason": reason,
        "extra": extra,
        "question_type": question_type
    }

    log_event(question_type, "ERROR", event)

def batch_write_logs(events):

    grouped = {}

    for event in events:
        qtype = event.get("question_type", "UNKNOWN")
        etype = event.get("type", "UNKNOWN")

        file_path = _get_log_file(qtype, etype)
        grouped.setdefault(file_path, []).append(event)

    for path, evts in grouped.items():

        existing = []
        if os.path.exists(path):
            try:
                with open(path, "rb") as f:
                    existing = orjson.loads(f.read())
            except (json.JSONDecodeError, OSError):
                existing = []

        existing.extend(evts)

        with open(path, "wb") as f:
            f.write(orjson.dumps(existing, option=orjson.OPT_INDENT_2))