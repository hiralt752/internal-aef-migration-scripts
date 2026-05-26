from app.clients.base_api_client import BaseApiClient
from app.core.logger import logger


class GetQuestionByIds:

    def __init__(self):
        self.api_client = BaseApiClient()

    async def get_question_data(self, question_id: str):

        endpoint = (
            f"assessment-question-service/api/questions/{question_id}"
        )

        logger.info(f"Fetching: {question_id}")

        return await self.api_client.get(endpoint)