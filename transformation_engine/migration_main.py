import asyncio
import json
import re
from datetime import datetime
from collections import defaultdict

from base_api_client import BaseApiClient

ENDPOINT = "https://ccl-rc-az.nprd.alefed.com/question-bank-service/api/v1/questions"


class PostApi:

    def __init__(self):
        self.client = BaseApiClient()
        self.results = defaultdict(list)

    async def post(self, payloads: dict | list[dict]):
        if isinstance(payloads, dict):
            payloads = [payloads]

        try:
            tasks = [self._post_question(p) for p in payloads]
            await asyncio.gather(*tasks)
        finally:
            await self.client.close()

        self._save_results()

        total = sum(len(v) for v in self.results.values())
        for status_code, items in self.results.items():
            print(f"  [{status_code}] : {len(items)} records")
        print(f"Total: {total}")

        return self.results

    async def _post_question(self, payload: dict):
        question_id = payload.get("metadata", {}).get("general", {}).get("externalId")
        subject = payload.get("metadata", {}).get("classification", {}).get("subject")
        question_type = payload.get("type")

        try:
            response = await self.client.post(ENDPOINT, payload=payload)
            self.results["SUCCESS"].append({
                "questionId": question_id,
                "subject": subject,
                "type": question_type,
                "status": "SUCCESS",
                "response": response,
                "timestamp": datetime.now().isoformat()
            })

        except Exception as e:
            status_code = self._extract_status_code(str(e))
            self.results[status_code].append({
                "questionId": question_id,
                "subject": subject,
                "type": question_type,
                "status": status_code,
                "response": str(e),
                "timestamp": datetime.now().isoformat()
            })

    def _extract_status_code(self, error_msg: str) -> str:
        match = re.search(r'Status:\s*(\d{3})', error_msg)
        return match.group(1) if match else "ERROR"

    def _save_results(self):
        for status_code, items in self.results.items():
            filename = f"{status_code}.json"
            with open(filename, "w") as f:
                json.dump(items, f, indent=2)
            print(f"Saved {filename} → {len(items)} records")