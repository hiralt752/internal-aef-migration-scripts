import json

STORED_QUESTION_IDS = set()


def load_question_ids_from_json(json_path):

    global STORED_QUESTION_IDS

    STORED_QUESTION_IDS.clear()

    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    for qid in data:
        qid = str(qid).strip()

        if qid:
            STORED_QUESTION_IDS.add(qid)

    return len(STORED_QUESTION_IDS)


def is_question_id_present(question_id):
    return str(question_id).strip() in STORED_QUESTION_IDS