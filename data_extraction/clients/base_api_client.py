import asyncio
import httpx
from app.core.config import settings


class BaseApiClient:

    def __init__(self):

        self.client = httpx.AsyncClient(
            base_url=settings.API_BASE_URL,
            headers={
                "Authorization": f"Bearer {settings.BEARER_TOKEN}",
                "X-Tenantid": "shared"
            },
            timeout=httpx.Timeout(30.0),
            limits=httpx.Limits(
                max_connections=20,
                max_keepalive_connections=10
            )
        )

    async def get(self, endpoint: str):

        for attempt in range(3):
            try:
                response = await self.client.get(endpoint)
                response.raise_for_status()
                return response.json()

            except (httpx.TimeoutException, httpx.RequestError):
                await asyncio.sleep(1 * (attempt + 1))

            except httpx.HTTPStatusError:
                raise

        raise Exception(f"Failed after retries: {endpoint}")

    async def close(self):
        await self.client.aclose()