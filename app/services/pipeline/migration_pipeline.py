import asyncio

from services.extraction.extraction_processor import (
    ExtractionProcessor
)


class MigrationPipeline:

    def run_extraction(
        self
    ):

        processor = (
            ExtractionProcessor()
        )

        asyncio.run(
            processor.run()
        )