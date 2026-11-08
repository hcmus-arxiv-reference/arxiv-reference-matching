import ast
import contextlib
import gzip
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

import arxiv


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
            "SUMMARY_OUTPUT_PATH": self.output_root / "summary.json",
            "BENCHMARK_OUTPUT_PATH": self.output_root / "benchmark.json",
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
            "done.json",
            "metadata.json",
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
            if vid == "2409.18594v1" and attempts[vid] == 1:
                raise HTTPError("https://export.arxiv.org/src/x", 429, "Too Many Requests", {}, None)
            if vid == "2409.18595v1" and attempts[vid] == 1:
                raise arxiv.HTTPError("https://export.arxiv.org/api/query", 0, 503)
            if vid == "2409.18596v1":
                raise HTTPError("https://export.arxiv.org/src/x", 404, "Not Found", {}, None)
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
