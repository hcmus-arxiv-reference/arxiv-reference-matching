import requests
from dotenv import load_dotenv
import os
import aiohttp
import asyncio


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
        request_url = self.url + paperID

        async with aiohttp.ClientSession() as session:
            async with session.get(
                    request_url,
                    params=self.query_params,
                    headers=self.headers
            ) as response:
                response.raise_for_status()
                return await response.json()


if __name__ == "__main__":
    load_dotenv()
    S2_API_KEY = os.getenv("S2_API_KEY1")
    s2 = S2_Request(str(S2_API_KEY))
    print(s2.send_request("2409.18594"))

