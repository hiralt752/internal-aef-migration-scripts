def make_unique_id(data) -> str:
    qid = data.get("question_id")

    if qid:
        return str(qid)

    return None