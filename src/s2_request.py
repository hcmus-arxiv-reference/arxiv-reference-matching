import requests
from dotenv import load_dotenv
import os
import aiohttp
import asyncio
from urllib.parse import quote


class S2_Request:
    def __init__(self, S2_API_KEY: str):
        self.headers = {"x-api-key": S2_API_KEY}
        self.url = "https://api.semanticscholar.org/graph/v1/paper/"
        self.query_params = {
            "fields": ",".join([
                "title",
                "abstract",
                "authors.name",
                "authors.affiliations",
                "references.title",
                "references.abstract"
            ])
        }

    def send_request(self, paperID: str):
        request_url = self.url + f"ARXIV:{paperID}"
        response = requests.get(request_url, params= self.query_params, headers= self.headers)

        if response.status_code == 200:
            res_data = response.json()
            print(res_data)
            return 200

        return response.status_code

    async def send_async_request(self, paperID: str):
        # https://api.semanticscholar.org/api-docs/graph
        request_url = self.url + f"ARXIV:{quote(paperID, safe='')}/references"
        references = []
        offset = 0
        params = {
            "fields": "paperId,title,authors,externalIds,year,publicationDate,venue",
            "limit": 1000,
        }
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=60)) as session:
            while True:
                await asyncio.sleep(1)
                params["offset"] = offset
                async with session.get(request_url, params=params, headers=self.headers) as response:
                    response.raise_for_status()
                    page = await response.json()
                references.extend(item.get("citedPaper") for item in page["data"])
                offset = page.get("next")
                if offset is None:
                    break
        return {"references": references}


if __name__ == "__main__":
    load_dotenv()
    S2_API_KEY = os.getenv("S2_API_KEY1")
    s2 = S2_Request(str(S2_API_KEY))
    print(s2.send_request("2409.18594"))

