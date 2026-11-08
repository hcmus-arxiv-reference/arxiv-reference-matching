import ast
import contextlib
import gzip
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import requests


class ArxivCrawlerBenchmarkNotebookTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.output_root = self.root / "output_json"
        self.temp_dir = self.root / "temp_scratch"
        self.ids_path = self.root / "ids.txt"
        self.notebook_path = Path(__file__).resolve().parents[1] / "src/arxiv_crawler_benchmark.ipynb"
        self.notebook = json.loads(self.notebook_path.read_text(encoding="utf-8"))

        self.namespace = {}
        self.execute_cell(1)
        self.namespace.update({
            "IDS_TXT_DIR": self.ids_path,
            "OUTPUT_ROOT": self.output_root,
            "TEMP_DIR": self.temp_dir,
            "CLEANUP_MODE": "immediate",
            "BATCH_SIZE": 2,
            "START_IDX": 0,
            "END_IDX": 10,
            "RETRY_ROUND_DELAY": 1,
            "MEMBER": "minh",
            "COLD_RUN": True,
            "BENCHMARK_INTERVAL": 0.05,
            "DISK_INTERVAL": 0.05,
            "METADATA_OUTPUT_DIR": self.output_root / "metadata.json",
            "STATUS_OUTPUT_PATH": self.output_root / "status.json",
            "DONE_OUTPUT_PATH": self.output_root / "done.json",
            "SKIPPED_OUTPUT_PATH": self.output_root / "skipped_ids.json",
            "PAPERS_STATS_OUTPUT_PATH": self.output_root / "papers_stats.json",
            "SUMMARY_OUTPUT_PATH": self.output_root / "summary.json",
            "BENCHMARK_OUTPUT_PATH": self.output_root / "benchmark.json",
            "BENCHMARK_SAMPLES_OUTPUT_PATH": self.output_root / "benchmark_samples.json",
            "CLAIM_OUTPUT_PATH": self.output_root / "benchmark.claim.json",
            "RUN_OUTPUT_PATH": self.output_root / "run.json",
        })
        self.execute_cell(2)
        self.execute_cell(3)
        self.execute_cell(4)
        for index in (5, 6):
            tree = ast.parse("".join(self.notebook["cells"][index]["source"]))
            definitions = ast.Module(
                body=[node for node in tree.body if isinstance(node, ast.FunctionDef)],
                type_ignores=[],
            )
            exec(compile(definitions, str(self.notebook_path), "exec"), self.namespace)
        self.log = io.StringIO()
        self.enterContext(contextlib.redirect_stdout(self.log))
        self.sleep = self.enterContext(patch.object(self.namespace["time"], "sleep"))

    def execute_cell(self, index):
        source = "".join(self.notebook["cells"][index]["source"])
        exec(compile(source, str(self.notebook_path), "exec"), self.namespace)

    def configure(self, ids, selected=None):
        self.ids_path.write_text("\n".join(ids) + "\n", encoding="utf-8")
        self.namespace["id_list"] = ids if selected is None else selected

    def mock_source(self, fetch):
        def download(arxiv_id, save_dir=None):
            target_dir = Path(save_dir or self.temp_dir)
            target_dir.mkdir(parents=True, exist_ok=True)
            payload = fetch(arxiv_id)
            (target_dir / f"{arxiv_id}.tar.gz").write_bytes(payload)
            return 200

        self.namespace["get_source"] = download

    @staticmethod
    def archive(files):
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
            for name, content in files.items():
                member = tarfile.TarInfo(name)
                member.size = len(content)
                archive.addfile(member, io.BytesIO(content))
        return buffer.getvalue()

    def test_outputs_only_json_files_and_cleans_up_temp_immediately(self):
        ids = ["2409.18594v1", "2409.18594v2", "2409.18595v1"]
        self.configure(ids)
        tex_v1 = b"\\documentclass{article}\n\\input{sub/part}\n"
        tar_payload = self.archive({
            "main.tex": tex_v1,
            "sub/part.tex": b"Body text.",
            "refs.bib": b"@article{a}",
            "figure.png": b"binary_image_bytes" * 50,
        })
        gz_payload = gzip.compress(b"\\documentclass{article}\nSingle file.")
        pdf_payload = b"%PDF-1.4\npdf_only_bytes"
        payloads = {
            "2409.18594v1": tar_payload,
            "2409.18594v2": gz_payload,
            "2409.18595v1": pdf_payload,
        }
        self.mock_source(payloads.__getitem__)
        results = self.namespace["crawl_sources"]()

        # Không sinh bất kỳ thư mục con hay file .tar.gz nào trong OUTPUT_ROOT
        output_items = sorted(p.name for p in self.output_root.iterdir())
        expected_jsons = sorted([
            "benchmark.claim.json",
            "benchmark.json",
            "benchmark_samples.json",
            "done.json",
            "metadata.json",
            "papers_stats.json",
            "run.json",
            "skipped_ids.json",
            "status.json",
            "summary.json",
        ])
        self.assertEqual(output_items, expected_jsons)
        self.assertTrue(all(p.is_file() and p.suffix == ".json" for p in self.output_root.iterdir()))
        self.assertFalse(self.temp_dir.exists())

        status_map = json.loads((self.output_root / "status.json").read_text(encoding="utf-8"))
        self.assertEqual(status_map["2409.18594v1"]["status"], "ok")
        self.assertEqual(status_map["2409.18594v1"]["kind"], "tar")
        self.assertEqual(set(status_map["2409.18594v1"]["files"]), {"main.tex", "sub/part.tex", "refs.bib"})
        self.assertEqual(status_map["2409.18594v2"]["status"], "ok")
        self.assertEqual(status_map["2409.18594v2"]["kind"], "gz_single")
        self.assertEqual(status_map["2409.18595v1"]["status"], "empty")
        self.assertEqual(status_map["2409.18595v1"]["kind"], "pdf")

        done_map = json.loads((self.output_root / "done.json").read_text(encoding="utf-8"))
        self.assertEqual(set(done_map), {"2409.18594", "2409.18595"})
        self.assertEqual(done_map["2409.18594"]["versions_with_tex"], 2)
        self.assertEqual(done_map["2409.18595"]["versions_with_tex"], 0)
        self.assertEqual(done_map["2409.18595"]["versions_non_tex"], 1)

        summary = results["summary"]
        self.assertEqual(summary["papers_requested"], 2)
        self.assertEqual(summary["papers_done"], 2)
        self.assertEqual(summary["versions_total"], 3)
        self.assertEqual(summary["versions_with_tex"], 2)
        self.assertEqual(summary["versions_non_tex"], 1)
        self.assertGreater(summary["size_reduction_pct"], 0)

        bench = results["benchmark"]
        self.assertIsNotNone(bench["peak_rss_mb"])
        self.assertIsNotNone(bench["avg_rss_mb"])
        self.assertIsNotNone(bench["peak_disk_mb"])
        self.assertEqual(bench["done_papers_at_end"], 2)

        claim = results["claim"]
        self.assertEqual(claim["schema_version"], 1)
        self.assertEqual(claim["ids_attempted"], 2)
        self.assertEqual(claim["totals"]["publications_complete"], 2)
        self.assertEqual(claim["totals"]["versions_ok"], 3)

    def test_batch_cleanup_and_retry_metrics_work(self):
        self.namespace["CLEANUP_MODE"] = "batch"
        self.namespace["BATCH_SIZE"] = 2
        ids = ["2409.18594v1", "2409.18595v1", "2409.18596v1"]
        self.configure(ids)
        attempts = dict.fromkeys(ids, 0)

        def fetch(vid):
            attempts[vid] += 1
            status = None
            if attempts[vid] == 1:
                status = {ids[0]: 429, ids[1]: 503}.get(vid)
            if vid == ids[2]:
                status = 404
            if status is not None:
                response = requests.Response()
                response.status_code = status
                raise requests.exceptions.HTTPError(response=response)
            return gzip.compress(b"\\documentclass{article}\nHello")

        self.mock_source(fetch)
        results = self.namespace["crawl_sources"]()
        http_stats = results["benchmark"]["http"]
        self.assertEqual(http_stats["requests"], 5)
        self.assertEqual(http_stats["retries"], 2)
        self.assertEqual(http_stats["retry_rounds"], 1)
        self.assertEqual(http_stats["http_429"], 1)
        self.assertEqual(http_stats["http_5xx"], 1)
        self.assertEqual(http_stats["errors_by_type"], {"429": 1, "503": 1, "404": 1})
        self.assertFalse(self.temp_dir.exists())

    def test_transport_errors_retry_after_the_current_pass(self):
        ids = [f"2409.{number}v1" for number in range(18594, 18599)]
        self.configure(ids)
        error_types = [
            requests.exceptions.ChunkedEncodingError,
            requests.exceptions.ConnectTimeout,
            requests.exceptions.ReadTimeout,
            requests.exceptions.ConnectionError,
            requests.exceptions.ContentDecodingError,
        ]
        errors = dict(zip(ids, error_types))
        calls = []

        def fetch(vid):
            calls.append(vid)
            if calls.count(vid) == 1:
                raise errors[vid]("interrupted response")
            return gzip.compress(b"\\documentclass{article}\nHello")

        self.mock_source(fetch)
        results = self.namespace["crawl_sources"]()

        self.assertEqual(calls, ids + ids)
        http_stats = results["benchmark"]["http"]
        self.assertEqual(http_stats["requests"], 10)
        self.assertEqual(http_stats["retries"], 5)
        self.assertEqual(http_stats["retry_rounds"], 1)
        self.assertEqual(http_stats["http_429"], 0)
        self.assertEqual(http_stats["http_5xx"], 0)
        self.assertEqual(http_stats["errors_by_type"], {error.__name__: 1 for error in error_types})
        self.assertEqual(results["summary"]["versions_failed"], 0)
        self.assertEqual(results["summary"]["papers_done"], len(ids))
        metadata = json.loads((self.output_root / "metadata.json").read_text())
        self.assertEqual([row["state"] for row in metadata], ["fail"] * 5 + ["success"] * 5)

    def test_transport_retry_limit_preserves_the_final_error(self):
        ids = ["2409.18594v1"]
        self.configure(ids)
        self.namespace["MAX_RETRY_ROUNDS"] = 2

        def fetch(vid):
            raise requests.exceptions.ChunkedEncodingError("interrupted response")

        self.mock_source(fetch)
        results = self.namespace["crawl_sources"]()

        http_stats = results["benchmark"]["http"]
        self.assertEqual(http_stats["requests"], 3)
        self.assertEqual(http_stats["retries"], 2)
        self.assertEqual(http_stats["retry_rounds"], 2)
        self.assertEqual(http_stats["errors_by_type"], {"ChunkedEncodingError": 3})
        self.assertEqual(results["summary"]["versions_failed"], 1)
        status = json.loads((self.output_root / "status.json").read_text())
        self.assertEqual(status[ids[0]]["error"], "ChunkedEncodingError")
        self.assertIn("còn 1 Version lỗi có thể thử lại", self.log.getvalue())
        self.assertFalse(self.temp_dir.exists())

    def test_retry_after_and_capped_backoff_across_multiple_rounds(self):
        ids = ["2409.18594v1"]
        self.configure(ids)
        self.namespace["RETRY_ROUND_DELAY"] = 2
        self.namespace["MAX_RETRY_DELAY"] = 3
        attempts = 0

        def fetch(vid):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                response = requests.Response()
                response.status_code = 429
                response.headers["Retry-After"] = "7"
                raise requests.exceptions.HTTPError(response=response)
            if attempts < 4:
                raise requests.exceptions.ChunkedEncodingError("interrupted response")
            return gzip.compress(b"\\documentclass{article}\nHello")

        self.mock_source(fetch)
        results = self.namespace["crawl_sources"]()

        self.assertEqual([call.args[0] for call in self.sleep.call_args_list], [7.0, 3, 3])
        http_stats = results["benchmark"]["http"]
        self.assertEqual(http_stats["retry_rounds"], 3)
        self.assertEqual(http_stats["backoff_seconds"], 13)
        self.assertEqual(http_stats["http_429"], 1)
        self.assertEqual(http_stats["http_5xx"], 0)
        self.assertEqual(results["summary"]["versions_failed"], 0)

    def test_permanent_http_and_local_write_errors_are_not_retried(self):
        ids = ["2409.18594v1", "2409.18595v1", "2409.18596v1"]
        self.configure(ids)

        def fetch(vid):
            if vid == ids[0]:
                raise OSError(28, "No space left on device")
            response = requests.Response()
            response.status_code = 403 if vid == ids[1] else 404
            raise requests.exceptions.HTTPError(response=response)

        self.mock_source(fetch)
        results = self.namespace["crawl_sources"]()

        http_stats = results["benchmark"]["http"]
        self.assertEqual(http_stats["requests"], 3)
        self.assertEqual(http_stats["retries"], 0)
        self.assertEqual(http_stats["retry_rounds"], 0)
        self.assertEqual(http_stats["errors_by_type"], {"OSError": 1, "403": 1, "404": 1})
        self.sleep.assert_not_called()

    def test_partial_stream_is_removed_before_retry_download(self):
        ids = ["2409.18594v1"]
        self.configure(ids)
        archive_path = self.temp_dir / f"{ids[0]}.tar.gz"
        payload = gzip.compress(b"\\documentclass{article}\nHello")

        def interrupted_stream():
            yield b"partial archive"
            self.assertTrue(archive_path.exists())
            raise requests.exceptions.ChunkedEncodingError("interrupted response")

        broken_response = MagicMock()
        broken_response.__enter__.return_value = broken_response
        broken_response.iter_content.return_value = interrupted_stream()
        good_response = MagicMock()
        good_response.__enter__.return_value = good_response
        good_response.status_code = 200
        good_response.iter_content.return_value = [payload]
        responses = iter([broken_response, good_response])

        def get_response(*args, **kwargs):
            self.assertFalse(archive_path.exists())
            return next(responses)

        with patch.object(self.namespace["HTTP_SESSION"], "get", side_effect=get_response) as get:
            results = self.namespace["crawl_sources"]()

        self.assertEqual(get.call_count, 2)
        self.assertEqual(results["benchmark"]["http"]["retries"], 1)
        self.assertEqual(results["summary"]["versions_with_tex"], 1)
        self.assertEqual(results["summary"]["versions_failed"], 0)
        self.assertFalse(self.temp_dir.exists())

    def test_tar_path_traversal_and_corrupt_gzip_are_marked_error(self):
        ids = ["2409.18594v1", "2409.18595v1"]
        self.configure(ids)
        bad_tar = self.archive({"../../../escaped.tex": b"unsafe"})
        bad_gz = gzip.compress(b"\\documentclass{article}\n" + b"body" * 1000)[:-5]
        payloads = {"2409.18594v1": bad_tar, "2409.18595v1": bad_gz}
        self.mock_source(payloads.__getitem__)

        results = self.namespace["crawl_sources"]()
        status_map = json.loads((self.output_root / "status.json").read_text(encoding="utf-8"))
        self.assertEqual(status_map["2409.18594v1"]["status"], "error")
        self.assertEqual(status_map["2409.18595v1"]["status"], "error")
        self.assertEqual(results["summary"]["papers_done"], 0)
        self.assertEqual(results["summary"]["papers_error"], 2)
        self.assertFalse((self.root / "escaped.tex").exists())


if __name__ == "__main__":
    unittest.main()
