import asyncio
import json
import re
from pathlib import Path

from app.repo.csv_repo import CSVRepo
from app.services.get_question_service import GetQuestionByIds
from app.core.logger import logger


class ProcessTheQuestionRetrivalFlow:

    @staticmethod
    def get_last_chunk_index(output_dir: Path) -> int:

        if not output_dir.exists():
            return 0

        pattern = re.compile(r"batch_(\d+)\.json")
        max_index = 0

        for file in output_dir.glob("batch_*.json"):
            match = pattern.search(file.name)
            if match:
                max_index = max(max_index, int(match.group(1)))

        return max_index

    @staticmethod
    async def process_csv(csv_path: Path):

        question_ids = list(CSVRepo.read_csv_file(csv_path))

        logger.info(f"Total Question IDs: {len(question_ids)}")

        service = GetQuestionByIds()

        output_dir = Path("datasource/structuredjson") / csv_path.stem
        output_dir.mkdir(parents=True, exist_ok=True)

        last_chunk = ProcessTheQuestionRetrivalFlow.get_last_chunk_index(output_dir)
        chunk_index = last_chunk + 1

        logger.info(f"Resuming from chunk: {chunk_index}")

        semaphore = asyncio.Semaphore(15)
        batch_size = 1000

        tasks = []
        results = []
        failed_records = []

        async def worker(qid: str, retries: int = 3):

            async with semaphore:

                for attempt in range(1, retries + 1):
                    try:
                        res = await service.get_question_data(qid)

                        return {
                            "question_id": qid,
                            "status": "success",
                            "response": res
                        }

                    except Exception as e:

                        logger.warning(
                            f"Attempt {attempt} failed for {qid}"
                        )

                        if attempt == retries:

                            return {
                                "question_id": qid,
                                "status": "failed",
                                "error": str(e)
                            }

                        await asyncio.sleep(1)

        for qid in enumerate(question_ids):

            tasks.append(worker(qid))

            if len(tasks) >= batch_size:

                logger.info(f"Processing chunk {chunk_index}")

                batch_result = await asyncio.gather(*tasks)

                success = [r for r in batch_result if r["status"] == "success"]
                failed = [r for r in batch_result if r["errorCode"] == 2001]

                file_path = output_dir / f"batch_{chunk_index}.json"

                with open(file_path, "w", encoding="utf-8") as f:
                    json.dump(batch_result, f, ensure_ascii=False)

                logger.info(
                    f"Chunk {chunk_index} done | "
                    f"Success={len(success)} | Failed={len(failed)}"
                )

                results.extend(success)
                failed_records.extend(failed)

                tasks = []
                chunk_index += 1

        if tasks:

            logger.info(f"Processing final chunk {chunk_index}")

            batch_result = await asyncio.gather(*tasks)

            success = [r for r in batch_result if r["status"] == "success"]
            failed = [r for r in batch_result if r["status"] == "failed"]

            file_path = output_dir / f"batch_{chunk_index}.json"

            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(batch_result, f, ensure_ascii=False)

            logger.info(
                f"Final chunk done | "
                f"Success={len(success)} | Failed={len(failed)}"
            )

            results.extend(success)
            failed_records.extend(failed)

        if failed_records:

            fail_file = output_dir / "failed_questions.json"

            with open(fail_file, "w", encoding="utf-8") as f:
                json.dump(failed_records, f, ensure_ascii=False)

            logger.info(f"Total failed: {len(failed_records)}")

        await service.api_client.close()

        return {
            "message": "completed",
            "total_success": len(results),
            "total_failed": len(failed_records),
            "output_dir": str(output_dir),
            "chunks_created": chunk_index
        }