import asyncio
import httpx
from config import settings


class BaseApiClient:

    def __init__(self):
        self.client = httpx.AsyncClient(
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {settings.BEARER_TOKEN}",
                "X-Tenantid":"shared"
            },
            timeout=httpx.Timeout(30.0),
            limits=httpx.Limits(
                max_connections=20,
                max_keepalive_connections=10
            )
        )

    async def post(self, endpoint: str, payload: dict, rate_limiter=None):
        for attempt in range(3):
            try:
                if rate_limiter is not None:
                    await rate_limiter.acquire()
                response = await self.client.post(endpoint, json=payload)
                response.raise_for_status()
                return response

            except (httpx.TimeoutException, httpx.RequestError) as e:
                if attempt < 2:
                    await asyncio.sleep(1 * (attempt + 1))
                else:
                    raise Exception(f"Failed after retries: {endpoint} | Error: {e}")

            except httpx.HTTPStatusError as e:
                raise Exception(
                    f"HTTP error on POST {endpoint} | "
                    f"Status: {e.response.status_code} | "
                    f"Response: {e.response.text}"
                )

    async def close(self):
        await self.client.aclose()