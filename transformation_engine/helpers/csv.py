import csv

# Global storage
STORED_QUESTION_IDS = set()


def load_question_ids_from_csv(csv_path, column_name="question_id"):
    """
    Load question IDs from a CSV file into memory.

    Args:
        csv_path (str): Path to CSV file.
        column_name (str): CSV column containing question IDs.

    Returns:
        int: Number of IDs loaded.
    """
    global STORED_QUESTION_IDS

    STORED_QUESTION_IDS.clear()

    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)

        for row in reader:
            qid = str(row.get(column_name, "")).strip()

            if qid:
                STORED_QUESTION_IDS.add(qid)

    return len(STORED_QUESTION_IDS)


def is_question_id_present(question_id):
    return str(question_id).strip() in STORED_QUESTION_IDS