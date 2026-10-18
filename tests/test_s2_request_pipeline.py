import contextlib
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp

from src.Database.sql_db import SQLite
from src import s2_request_pipeline as pipeline
from src.s2_request import S2_Request


class PipelineTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.db_path = self.root / "data.sqlite3"
        connection = sqlite3.connect(self.db_path)
        with patch("src.Database.sql_db.sqlite3.connect", return_value=connection):
            self.db = SQLite()
        self.addCleanup(connection.close)
        self.db.init_table()
        with connection:
            connection.executemany(
                "INSERT INTO PAPERS (arxiv_id, version, submission_date, revised_date) VALUES (?, ?, ?, ?)",
                [("2409.18594", "2409.18594v2", "2024-09-27", "2025-05-27"),
                 ("2409.18594", "2409.18594v1", "2024-09-27", None),
                 ("1706.03762", "1706.03762v7", "2017-06-12", "2023-01-01"),
                 ("hep-th/9901001", "hep-th/9901001v1", "1999-01-01", None)],
            )
        self.metadata = {"references": [
            {"paperId": "example-s2", "externalIds": {"ArXiv": "1706.03762"},
             "title": "A reference's title", "authors": [{"name": "Nguyễn Văn A"}],
             "publicationDate": "2018-01-01"},
            {"paperId": "non-arxiv", "externalIds": {"DOI": "example"}, "title": "Other"},
            None,
            {"paperId": "unknown-date", "externalIds": {"ArXiv": "math/0301001"},
             "title": "Legacy", "authors": None},
        ]}
        self.crawlers = [MagicMock(send_async_request=AsyncMock(return_value=self.metadata)) for _ in range(3)]

    async def run_pipeline(self, ids):
        with patch.object(pipeline, "DB_PATH", self.db_path), \
                patch.object(pipeline, "METADATA_DIR", self.root / "metadata"), \
                patch.object(pipeline, "ref_ids", ids), \
                patch.object(pipeline, "crawlers", self.crawlers), \
                contextlib.redirect_stdout(io.StringIO()):
            return await pipeline.main()

    async def test_json_keeps_all_references_sql_keeps_only_arxiv_and_rerun_is_safe(self):
        results = await self.run_pipeline(["2409.18594"])
        self.assertEqual(results["2409.18594"], self.metadata)
        raw = json.loads((self.root / "metadata/2409.18594.json").read_text())
        self.assertEqual(raw, self.metadata)
        self.assertEqual(len(self.db.get_references("2409.18594")), 2)
        row = self.db.get_reference("2409.18594", "1706.03762")
        self.assertEqual(row, ("2409.18594", "2409.18594v2", "1706.03762",
                               "A reference's title", ["Nguyễn Văn A"], "2017-06-12", "example-s2"))
        legacy = self.db.get_reference("2409.18594", "math/0301001")
        self.assertIsNone(legacy[4])
        self.assertIsNone(legacy[5])
        await self.run_pipeline(["2409.18594"])
        self.assertEqual(len(self.db.get_references("2409.18594")), 2)

    async def test_three_crawlers_share_distinct_database_ids(self):
        results = await self.run_pipeline([])
        self.assertEqual(set(results), {"2409.18594", "1706.03762", "hep-th/9901001"})
        assigned = [call.args[0] for crawler in self.crawlers for call in crawler.send_async_request.await_args_list]
        self.assertEqual(len(assigned), 3)
        self.assertEqual(set(assigned), set(results))
        self.assertTrue(all(crawler.send_async_request.await_count == 1 for crawler in self.crawlers))
        self.assertTrue((self.root / "metadata/hep-th_9901001.json").exists())

    async def test_network_failure_does_not_stop_other_workers(self):
        self.crawlers[0].send_async_request.side_effect = aiohttp.ClientError("network")
        results = await self.run_pipeline(["2409.18594", "1706.03762", "hep-th/9901001"])
        self.assertIsNone(results["2409.18594"])
        self.assertEqual(results["1706.03762"], self.metadata)
        self.assertEqual(results["hep-th/9901001"], self.metadata)
        self.assertFalse((self.root / "metadata/2409.18594.json").exists())

    async def test_s2_request_collects_all_pages_with_same_public_method(self):
        pages = [{"data": [{"citedPaper": self.metadata["references"][1]}], "next": 1000},
                 {"data": [{"citedPaper": self.metadata["references"][0]}, {"citedPaper": None}]}]
        session = MagicMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=None)
        offsets = []

        def get(url, params, headers):
            offsets.append(params["offset"])
            self.assertTrue(url.endswith("/paper/ARXIV:hep-th%2F9901001/references"))
            self.assertEqual(headers, {"x-api-key": "synthetic-key"})
            self.assertEqual(params["fields"], "paperId,title,authors,externalIds,year,publicationDate,venue")
            response = MagicMock()
            response.__aenter__ = AsyncMock(return_value=response)
            response.__aexit__ = AsyncMock(return_value=None)
            response.json = AsyncMock(return_value=pages.pop(0))
            return response

        session.get.side_effect = get
        with patch("src.s2_request.aiohttp.ClientSession", return_value=session), \
                patch("src.s2_request.asyncio.sleep", new_callable=AsyncMock) as sleep:
            data = await S2_Request("synthetic-key").send_async_request("hep-th/9901001")
        self.assertEqual(offsets, [0, 1000])
        self.assertEqual(data["references"], [self.metadata["references"][1], self.metadata["references"][0], None])
        self.assertEqual(sleep.await_count, 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
