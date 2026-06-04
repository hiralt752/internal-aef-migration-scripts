import asyncio
import aiohttp

from tqdm.asyncio import tqdm

from clients.source_client import (
    SourceClient
)

from config.constants import (
    CONCURRENT_REQUESTS
)

from config.logging_config import (
    get_extraction_logger
)


logger = get_extraction_logger()


class QuestionFetcher:

    def __init__(self):

        self.semaphore = (
            asyncio.Semaphore(
                CONCURRENT_REQUESTS
            )
        )

    async def _fetch_with_limit(
        self,
        session,
        question_id
    ):

        async with self.semaphore:

            return (
                await SourceClient
                .fetch_question(
                    session,
                    question_id
                )
            )

    async def fetch_questions(
        self,
        question_ids,
        subject_name
    ):
        """
        Fetch a batch of questions.

        Returns:

        [
            {
                ...
            }
        ]
        """

        connector = (
            aiohttp.TCPConnector(
                limit=CONCURRENT_REQUESTS,
                ssl=False,
                force_close=True
            )
        )

        timeout = (
            aiohttp.ClientTimeout(
                total=None,
                sock_connect=60,
                sock_read=60
            )
        )

        async with aiohttp.ClientSession(
            connector=connector,
            timeout=timeout
        ) as session:

            tasks = [

                self._fetch_with_limit(
                    session,
                    question_id
                )

                for question_id
                in question_ids
            ]

            responses = []

            try:
            

                for future in tqdm.as_completed(
                    tasks,
                    desc=(
                        f"{subject_name}"
                    )
                ):

                    result = await future

                    if result:
                        responses.append(
                            result
                        )
            except asyncio.CancelledError:

                raise KeyboardInterrupt()

            logger.info(
                f"{subject_name}: "
                f"Fetched "
                f"{len(responses)} "
                f"questions"
            )

            return responses