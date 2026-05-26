import csv
from pathlib import Path

from app.core.logger import logger

csv.field_size_limit(2**31 - 1)


class CSVRepo:

    @staticmethod
    def read_csv_file(csv_file_path: Path):

        logger.info(f"Reading CSV: {csv_file_path}")

        question_ids = set()

        encodings = ["utf-16", "utf-8-sig", "utf-8", "latin-1"]

        for encoding in encodings:

            try:
                with open(csv_file_path, "r", encoding=encoding, errors="ignore") as file:

                    cleaned_lines = (line.replace("\x00", "") for line in file)

                    sample = "".join([next(cleaned_lines, "") for _ in range(5)])

                    file.seek(0)

                    cleaned_lines = (line.replace("\x00", "") for line in file)

                    dialect = csv.Sniffer().sniff(sample)

                    reader = csv.DictReader(cleaned_lines, dialect=dialect)

                    for row in reader:

                        if not row:
                            continue

                        normalized = {
                            str(k).strip().lower(): v
                            for k, v in row.items()
                            if k
                        }

                        qid = (
                            normalized.get("question id")
                            or normalized.get("questionid")
                            or normalized.get("question_id")
                        )

                        if qid:
                            question_ids.add(qid.strip())

                if question_ids:
                    logger.info(f"Parsed using {encoding}")
                    break

            except Exception as e:
                logger.warning(f"Encoding failed {encoding}: {str(e)}")

        if not question_ids:
            raise Exception("Invalid CSV")

        return question_ids