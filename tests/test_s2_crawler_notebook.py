import ast
import asyncio
import contextlib
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import quote

import aiohttp


class NotebookBatchTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.output = Path(temporary.name) / "metadata.json"
        notebook_path = Path(__file__).resolve().parents[1] / "src/S2_Crawler.ipynb"
        notebook = json.loads(notebook_path.read_text())
        source = notebook["cells"][2]["source"]
        tree = ast.parse("".join(source))
        # Load notebook functions without reading credentials or starting a crawl.
        functions = ast.Module(
            body=[node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))],
            type_ignores=[],
        )
        self.namespace = {
            "asyncio": asyncio, "aiohttp": aiohttp, "json": json,
            "METADATA_PATH": self.output, "BATCH_SIZE": 2,
            "quote": quote, "RETRY_ROUND_DELAY": 1,
        }
        exec(compile(functions, str(notebook_path), "exec"), self.namespace)
        request_tree = ast.parse("".join(notebook["cells"][1]["source"]))
        request_definitions = ast.Module(
            body=[node for node in request_tree.body if isinstance(node, (ast.FunctionDef, ast.ClassDef))],
            type_ignores=[],
        )
        exec(compile(request_definitions, str(notebook_path), "exec"), self.namespace)
        self.log = io.StringIO()
        self.enterContext(contextlib.redirect_stdout(self.log))
        self.sleep = self.enterContext(patch.object(asyncio, "sleep", new_callable=AsyncMock))

    def configure(self, ids, fetch, worker_count=2):
        self.namespace["ref_ids"] = ids
        self.namespace["crawlers"] = [
            SimpleNamespace(send_async_request=AsyncMock(side_effect=fetch))
            for _ in range(worker_count)
        ]

    async def test_saves_each_batch_before_next_batch_and_keeps_final_remainder(self):
        ids = [f"2508.{i:05d}" for i in range(5)]

        async def fetch(paper_id):
            index = ids.index(paper_id)
            if index >= 2:
                saved = json.loads(self.output.read_text())
                self.assertEqual(set(saved), set(ids[:index // 2 * 2]))
            return {"references": [{"title": "Tiêu đề"}]}

        self.configure(ids, fetch)
        results = await self.namespace["main"]()
        self.assertEqual(json.loads(self.output.read_text()), results)
        self.assertEqual(set(results), set(ids))
        self.assertEqual(self.log.getvalue().count("[SAVED]"), 3)
        self.assertIn(str(self.output.resolve()), self.log.getvalue())
        self.assertIn("Tiêu đề", self.output.read_text())
        self.assertFalse(self.output.with_suffix(".json.tmp").exists())

    async def test_http_timeout_and_connection_errors_are_logged_and_saved(self):
        url = "https://api.semanticscholar.org/graph/v1/paper/ARXIV:2508.00000/references"
        errors = {
            "2508.00000": aiohttp.ClientResponseError(
                SimpleNamespace(real_url=url), (), status=404,
                message="Not Found",
            ),
            "2508.00001": asyncio.TimeoutError(),
            "2508.00002": aiohttp.ClientConnectionError("Connection reset by peer"),
        }

        async def fetch(paper_id):
            if paper_id in errors:
                raise errors[paper_id]
            return {"references": []}

        self.configure([*errors, "2508.00003"], fetch)
        results = await self.namespace["main"]()
        self.assertEqual(json.loads(self.output.read_text()), results)
        self.assertTrue(all(results[paper_id] is None for paper_id in errors))
        self.assertEqual(results["2508.00003"], {"references": []})
        log = self.log.getvalue()
        for detail in ("404", "Not Found", url, "TimeoutError", "Request timed out", "Connection reset by peer"):
            self.assertIn(detail, log)

    def mock_session(self, outcomes):
        session = MagicMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=None)
        offsets = []

        def get(url, params, headers):
            offsets.append(params["offset"])
            outcome = outcomes.pop(0)
            response = MagicMock()
            response.__aenter__ = AsyncMock(return_value=response)
            response.__aexit__ = AsyncMock(return_value=None)
            if isinstance(outcome, Exception):
                response.raise_for_status.side_effect = outcome
            else:
                response.json = AsyncMock(return_value=outcome)
            return response

        session.get.side_effect = get
        self.enterContext(patch.object(aiohttp, "ClientSession", return_value=session))
        return offsets

    def http_error(self, status, headers=None):
        return aiohttp.ClientResponseError(
            SimpleNamespace(real_url="https://api.semanticscholar.org/graph/v1/paper/ARXIV:2508.00000/references"),
            (), status=status, message=f"HTTP {status}", headers=headers,
        )

    async def test_request_collects_all_pages_without_retrying_inline(self):
        first = {"paperId": "first"}
        second = {"paperId": "second"}
        offsets = self.mock_session([
            {"data": [{"citedPaper": first}], "next": 1000},
            {"data": [{"citedPaper": second}]},
        ])
        crawler = self.namespace["S2_Request"]("synthetic-key")
        result = await crawler.send_async_request("2508.00000")
        self.assertEqual(result, {"references": [first, second]})
        self.assertEqual(offsets, [0, 1000])

    async def test_first_pass_finishes_before_retry_rounds_with_fixed_delay(self):
        ids = [f"2508.{i:05d}" for i in range(4)]
        calls = []
        attempts = dict.fromkeys(ids, 0)

        async def fetch(paper_id):
            calls.append(paper_id)
            attempts[paper_id] += 1
            if attempts[paper_id] > 1:
                self.assertTrue(all(count >= 1 for count in attempts.values()))
                self.assertEqual(set(json.loads(self.output.read_text())), set(ids))
            if paper_id == ids[0] and attempts[paper_id] <= 2:
                raise self.http_error(429, {"Retry-After": "120"})
            if paper_id == ids[1] and attempts[paper_id] <= 2:
                raise self.http_error(503)
            if paper_id == ids[2]:
                raise self.http_error(404)
            return {"references": []}

        self.configure(ids, fetch, worker_count=1)
        results = await self.namespace["main"]()
        self.assertEqual(calls, ids + ids[:2] + ids[:2])
        self.assertEqual(json.loads(self.output.read_text()), results)
        self.assertIsNone(results[ids[2]])
        self.assertTrue(all(results[paper_id] is not None for paper_id in (ids[0], ids[1], ids[3])))
        self.assertEqual(self.log.getvalue().count("[RETRY]"), 2)
        self.assertTrue(all(call.args[0] == 1 for call in self.sleep.await_args_list))

    async def test_retry_rounds_have_no_attempt_limit(self):
        attempts = 0

        async def fetch(paper_id):
            nonlocal attempts
            attempts += 1
            if attempts <= 8:
                raise self.http_error(503)
            return {"references": []}

        self.configure(["2508.00000"], fetch)
        results = await self.namespace["main"]()
        self.assertEqual(attempts, 9)
        self.assertEqual(results, {"2508.00000": {"references": []}})
        self.assertEqual(self.log.getvalue().count("[RETRY]"), 8)
        self.assertTrue(all(call.args[0] == 1 for call in self.sleep.await_args_list))

    async def test_request_passes_all_http_errors_to_worker_without_inline_retry(self):
        for status in (400, 401, 403, 404, 408, 422, 429, 500, 503, 599, 600):
            with self.subTest(status=status):
                offsets = self.mock_session([self.http_error(status)])
                with self.assertRaises(aiohttp.ClientResponseError) as caught:
                    await self.namespace["S2_Request"]("synthetic-key").send_async_request("2508.00000")
                self.assertEqual(caught.exception.status, status)
                self.assertEqual(offsets, [0])

    async def test_worker_retries_only_429_and_5xx(self):
        statuses = (400, 401, 403, 404, 408, 422, 429, 500, 503, 599, 600)
        ids = [f"2508.{i:05d}" for i in range(len(statuses))]
        attempts = dict.fromkeys(ids, 0)

        async def fetch(paper_id):
            attempts[paper_id] += 1
            if attempts[paper_id] == 1:
                raise self.http_error(statuses[ids.index(paper_id)])
            return {"references": []}

        self.configure(ids, fetch)
        results = await self.namespace["main"]()
        for paper_id, status in zip(ids, statuses):
            retryable = status == 429 or 500 <= status < 600
            self.assertEqual(attempts[paper_id], 2 if retryable else 1)
            self.assertEqual(results[paper_id], {"references": []} if retryable else None)

    async def test_cancellation_during_retry_saves_new_success_with_same_id_count(self):
        ids = ["2508.00000", "2508.00001"]
        attempts = dict.fromkeys(ids, 0)
        second_started = asyncio.Event()

        async def fetch(paper_id):
            attempts[paper_id] += 1
            if attempts[paper_id] == 1:
                raise self.http_error(503)
            if paper_id == ids[1]:
                second_started.set()
                await asyncio.Event().wait()
            return {"references": []}

        self.configure(ids, fetch, worker_count=1)
        task = asyncio.create_task(self.namespace["main"]())
        await asyncio.wait_for(second_started.wait(), timeout=2)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(json.loads(self.output.read_text()), {
            ids[0]: {"references": []}, ids[1]: None,
        })

    async def test_cancellation_saves_completed_ids_in_partial_batch(self):
        second_started = asyncio.Event()

        async def fetch(paper_id):
            if paper_id == "2508.00001":
                second_started.set()
                await asyncio.Event().wait()
            return {"references": []}

        self.configure(["2508.00000", "2508.00001"], fetch, worker_count=1)
        task = asyncio.create_task(self.namespace["main"]())
        await asyncio.wait_for(second_started.wait(), timeout=2)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(json.loads(self.output.read_text()), {"2508.00000": {"references": []}})

    async def test_empty_input_writes_valid_json(self):
        self.configure([], AsyncMock())
        self.assertEqual(await self.namespace["main"](), {})
        self.assertEqual(json.loads(self.output.read_text()), {})


if __name__ == "__main__":
    unittest.main()
