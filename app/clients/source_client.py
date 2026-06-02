import asyncio

from config.constants import (
    MAX_RETRIES
)

from config.logging_config import (
    get_extraction_logger
)

from config.settings import (
    SOURCE_BASE_URL,
    BEARER_TOKEN
)

from utils.retry_utils import (
    get_backoff_delay
)


logger = get_extraction_logger()


class SourceClient:

    RETRYABLE_STATUS_CODES = [
        429,
        500,
        502,
        503,
        504
    ]

    @staticmethod
    async def fetch_question(
        session,
        question_id
    ):
        """
        Fetch a single question.

        Includes:
        - Retry handling
        - Exponential backoff
        - Jitter
        """

        url = SOURCE_BASE_URL.format(
            question_id
        )

        headers = {
            "Content-Type": "application/json",
            "Authorization": (
                f"Bearer {BEARER_TOKEN}"
            )
        }

        for attempt in range(
            MAX_RETRIES
        ):

            try:

                async with session.get(
                    url,
                    headers=headers
                ) as response:

                    status = response.status

                    try:
                        data = (
                            await response.json()
                        )

                    except Exception:
                        data = (
                            await response.text()
                        )

                    # ======================
                    # SUCCESS
                    # ======================

                    if status == 200:

                        return {
                            "question_id": question_id,
                            "status_code": status,
                            "response": data
                        }

                    # ======================
                    # RETRYABLE
                    # ======================

                    if (
                        status
                        in SourceClient
                        .RETRYABLE_STATUS_CODES
                    ):

                        wait_time = (
                            get_backoff_delay(
                                attempt
                            )
                        )

                        logger.warning(
                            f"Retrying "
                            f"{question_id} | "
                            f"Status={status} | "
                            f"Attempt={attempt + 1}"
                        )

                        await asyncio.sleep(
                            wait_time
                        )

                        continue

                    # ======================
                    # NON RETRYABLE
                    # ======================

                    logger.error(
                        f"Question "
                        f"{question_id} "
                        f"failed with "
                        f"status {status}"
                    )

                    return {
                        "question_id": question_id,
                        "status_code": status,
                        "response": data,
                        "error": (
                            f"HTTP {status}"
                        )
                    }

            except Exception as exc:

                wait_time = (
                    get_backoff_delay(
                        attempt
                    )
                )

                logger.exception(
                    f"Exception for "
                    f"{question_id}"
                )

                await asyncio.sleep(
                    wait_time
                )

        logger.error(
            f"{question_id} "
            f"failed after "
            f"{MAX_RETRIES} retries"
        )

        return {
            "question_id": question_id,
            "status_code": None,
            "error": (
                f"Failed after "
                f"{MAX_RETRIES} retries"
            )
        }