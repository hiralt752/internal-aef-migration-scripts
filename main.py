from pathlib import Path
from fastapi import FastAPI
from app.services.processing_service import ProcessTheQuestionRetrivalFlow
from app.core.logger import logger

app = FastAPI()


@app.post("/process-csv")
async def process_csv():
    logger.info("API /process-csv started")

    csv_files = Path("datasource/csv").glob("*.csv")

    results = []

    for file in csv_files:
        logger.info(f"Processing file: {file}")

        try:
            result = await ProcessTheQuestionRetrivalFlow.process_csv(file)
            results.append(result)

        except Exception as e:
            logger.exception(f"Error processing file {file}: {str(e)}")

    return {
        "message": "Processing completed",
        "files_processed": results
    }