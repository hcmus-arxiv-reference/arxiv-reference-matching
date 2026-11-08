import ast
import contextlib
import gzip
import io
import json
from pathlib import Path
import tarfile
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError, URLError

import arxiv
import requests


class ArxivNotebookTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.output = self.root / "output"
        self.output.mkdir()
        self.ids_path = self.root / "ids.txt"
        self.metadata = self.root / "metadata.json"
        self.notebook_path = Path(__file__).resolve().parents[1] / "src/arxiv_crawler.ipynb"
        self.notebook = json.loads(self.notebook_path.read_text())
        self.namespace = {
            "SAVE_DIR": str(self.output), "METADATA_OUTPUT_DIR": str(self.metadata),
            "IDS_TXT_DIR": str(self.ids_path), "RETRY_ROUND_DELAY": 1,
            "START_IDX": 0, "END_IDX": 10,
        }
        self.execute_cell(2)
        self.execute_cell(3)
        for index in (4, 5):
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

    def version_dir(self, paper_id):
        return self.namespace["version_output"](paper_id)[2]

    def status(self, paper_id):
        return json.loads((self.version_dir(paper_id) / "status.json").read_text())

    def mock_source(self, fetch):
        def download(arxiv_id, save_dir):
            payload = fetch(arxiv_id)
            (Path(save_dir) / f"{arxiv_id}.tar.gz").write_bytes(payload)
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

    def test_retry_rounds_finish_the_whole_pass_and_preserve_metadata(self):
        ids = [f"2508.{index:05d}v1" for index in range(4)]
        self.configure(ids)
        calls = []
        attempts = dict.fromkeys(ids, 0)

        def fetch(paper_id):
            calls.append(paper_id)
            attempts[paper_id] += 1
            if attempts[paper_id] > 1:
                self.assertTrue(all(attempts.values()))
                saved = json.loads(self.metadata.read_text())
                self.assertTrue(set(ids).issubset(row["id"] for row in saved))
            if paper_id == ids[0] and attempts[paper_id] <= 2:
                raise HTTPError("https://export.arxiv.org/src/example", 429, "Busy", {}, None)
            if paper_id == ids[1] and attempts[paper_id] <= 2:
                raise arxiv.HTTPError("https://export.arxiv.org/api/query", 0, 503)
            if paper_id == ids[2]:
                raise HTTPError("https://export.arxiv.org/src/example", 404, "Missing", {}, None)
            return b"%PDF-1.4\nexample"

        self.mock_source(fetch)
        self.namespace["crawl_sources"]()
        self.assertEqual(calls, ids + ids[:2] + ids[:2])
        saved = json.loads(self.metadata.read_text())
        self.assertEqual(len(saved), 8)
        self.assertTrue(all(set(row) == {"id", "path", "state"} for row in saved))
        last = {row["id"]: row["state"] for row in saved}
        self.assertEqual(last, {pid: "fail" if pid == ids[2] else "success" for pid in ids})
        self.assertEqual(self.status(ids[2])["status"], "error")
        self.assertEqual(self.status(ids[0])["status"], "downloaded")
        self.assertEqual([call.args[0] for call in self.sleep.call_args_list], [1, 1])

    def test_retry_has_no_attempt_limit(self):
        paper_id = "2508.00001v1"
        self.configure([paper_id])
        attempts = 0

        def fetch(_):
            nonlocal attempts
            attempts += 1
            if attempts <= 8:
                raise HTTPError("https://export.arxiv.org/src/example", 503, "Busy", {}, None)
            return b"%PDF-1.4"

        self.mock_source(fetch)
        self.namespace["crawl_sources"]()
        self.assertEqual(attempts, 9)
        self.assertEqual(self.sleep.call_count, 8)

    def test_retries_only_429_and_5xx_like_s2(self):
        errors = [
            HTTPError("https://export.arxiv.org/src/example", code, "HTTP error", {}, None)
            for code in (400, 403, 404, 408, 429, 500, 599, 600)
        ] + [TimeoutError(), URLError("Connection reset"), StopIteration()]
        ids = [f"2508.{index:05d}v1" for index in range(len(errors))]
        self.configure(ids)
        attempts = dict.fromkeys(ids, 0)

        def fetch(paper_id):
            attempts[paper_id] += 1
            if attempts[paper_id] == 1:
                raise errors[ids.index(paper_id)]
            return b"%PDF-1.4"

        self.mock_source(fetch)
        self.namespace["crawl_sources"]()
        for index, paper_id in enumerate(ids):
            self.assertEqual(attempts[paper_id], 2 if index in (4, 5, 6) else 1)

    def test_requests_http_error_is_retried(self):
        paper_id = "2508.00001v1"
        self.configure([paper_id])
        response = requests.Response()
        response.status_code = 503
        error = requests.exceptions.HTTPError(response=response)
        outcomes = iter([error, b"%PDF-1.4"])

        def fetch(_):
            outcome = next(outcomes)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        self.mock_source(fetch)
        self.namespace["crawl_sources"]()
        self.assertEqual(self.status(paper_id)["status"], "downloaded")
        self.assertEqual(self.sleep.call_count, 1)

    def test_source_download_keeps_endpoint_archive_and_sleeps_two_seconds(self):
        paper_id = "2508.00001v1"
        client = MagicMock()
        client.results.return_value = iter([SimpleNamespace(title="Example", get_short_id=lambda: paper_id)])
        self.namespace["client"] = client
        payload = b"archive bytes"
        with patch.object(self.namespace["urllib"].request, "urlopen", return_value=io.BytesIO(payload)) as fetch:
            self.assertEqual(self.namespace["get_source"](paper_id), 200)
        self.assertEqual((self.output / f"{paper_id}.tar.gz").read_bytes(), payload)
        fetch.assert_called_once_with(f"https://export.arxiv.org/src/{paper_id}", timeout=60)
        self.sleep.assert_called_once_with(2)

    def test_download_failure_also_sleeps_two_seconds(self):
        self.namespace["client"] = MagicMock()
        self.namespace["client"].results.return_value = iter([])
        with self.assertRaises(StopIteration):
            self.namespace["get_source"]("2508.00001v1")
        self.sleep.assert_called_once_with(2)

    def test_batch_checkpoint_and_interruption_keep_completed_ids(self):
        ids = [f"2508.{index:05d}v1" for index in range(102)]
        self.configure(ids)

        def fetch(paper_id):
            index = ids.index(paper_id)
            if index == 100:
                self.assertEqual(len(json.loads(self.metadata.read_text())), 100)
            if index == 101:
                raise KeyboardInterrupt()
            return b"%PDF-1.4"

        self.mock_source(fetch)
        with self.assertRaises(KeyboardInterrupt):
            self.namespace["crawl_sources"]()
        self.assertEqual(len(json.loads(self.metadata.read_text())), 101)

    def test_tar_preserves_source_and_nested_paths_and_adds_status_and_done(self):
        ids = ["2508.00001v1", "2508.00001v2"]
        self.configure(ids)
        tex = b"\\documentclass{article}\n\\includegraphics{fig.png}\n\\input{nested/body}\n"
        files = {"main.tex": tex, "nested/body.tex": b"Text.", "refs.bib": b"@article{x}", "fig.png": b"image"}
        payload = self.archive(files)
        self.mock_source(lambda _: payload)
        self.namespace["crawl_sources"]()
        paper_dir = self.version_dir(ids[0]).parent
        self.assertFalse((paper_dir / "done.json").exists())
        self.execute_cell(6)
        for paper_id in ids:
            version_dir = self.version_dir(paper_id)
            record = self.status(paper_id)
            self.assertEqual(record["kind"], "tar")
            self.assertEqual(record["status"], "ok")
            self.assertEqual(set(record["files"]), set(files) - {"fig.png"})
            self.assertEqual((version_dir / "main.tex").read_bytes(), tex)
            self.assertEqual((version_dir / "nested/body.tex").read_bytes(), b"Text.")
            self.assertFalse((version_dir / "fig.png").exists())
            self.assertEqual(record["bytes_downloaded"], len(payload))
            self.assertEqual(record["bytes_before"], sum(map(len, files.values())))
            self.assertEqual(record["bytes_after"], sum(len(content) for name, content in files.items() if name != "fig.png"))
            self.assertTrue((self.output / f"{paper_id}.tar.gz").exists())
        done = json.loads((paper_dir / "done.json").read_text())
        self.assertEqual((done["id"], done["status"], done["n_versions"], done["versions_with_tex"]), ("2508.00001", "done", 2, 2))
        self.assertFalse(list(self.output.rglob("*.tmp")))

    def test_empty_versions_remain_in_status_and_done(self):
        ids = [f"2508.00001v{index}" for index in range(1, 6)]
        self.configure(ids)
        payloads = dict(zip(ids, [
            b"%PDF-1.4\nexample", gzip.compress(b"%PDF-1.4\nexample"),
            gzip.compress(b"plain text without LaTeX"), b"unsupported format",
            self.archive({"fig.png": b"image"}),
        ]))
        self.mock_source(payloads.__getitem__)
        self.namespace["crawl_sources"]()
        self.execute_cell(6)
        for paper_id in ids:
            record = self.status(paper_id)
            self.assertEqual((record["status"], record["files"]), ("empty", []))
            self.assertFalse((self.version_dir(paper_id) / "main.tex").exists())
        done = json.loads((self.version_dir(ids[0]).parent / "done.json").read_text())
        self.assertEqual((done["n_versions"], done["versions_with_tex"]), (5, 0))
        self.assertEqual((self.output / "pass.txt").read_text().splitlines(), ids[:4])

    def test_gzip_tex_is_unchanged_and_partial_slice_is_not_done(self):
        ids = ["2508.00001v1", "2508.00001v2"]
        self.configure(ids, selected=ids[:1])
        tex = b"\\documentclass{article}\n" + b"Original content.\n" * 2000
        self.mock_source(lambda _: gzip.compress(tex))
        self.namespace["crawl_sources"]()
        self.execute_cell(6)
        self.assertEqual((self.version_dir(ids[0]) / "main.tex").read_bytes(), tex)
        record = self.status(ids[0])
        self.assertEqual((record["kind"], record["files"]), ("gz_single", ["main.tex"]))
        self.assertEqual(record["bytes_before"], len(tex))
        self.assertFalse((self.version_dir(ids[0]).parent / "done.json").exists())

    def test_bad_archive_does_not_mark_publication_done_or_leave_temporary_files(self):
        paper_id = "2508.00001v1"
        self.configure([paper_id])
        damaged = gzip.compress(b"\\documentclass{article}\n" + b"content" * 5000)[:-4]
        self.mock_source(lambda _: damaged)
        self.namespace["crawl_sources"]()
        self.execute_cell(6)
        self.assertEqual(self.status(paper_id)["status"], "error")
        self.assertFalse((self.version_dir(paper_id).parent / "done.json").exists())
        self.assertEqual([p.name for p in self.version_dir(paper_id).iterdir()], ["status.json"])

    def test_tar_path_traversal_is_rejected_and_not_done(self):
        paper_id = "2508.00001v1"
        self.configure([paper_id])
        self.mock_source(lambda _: self.archive({"../../../escaped.tex": b"unsafe"}))
        self.namespace["crawl_sources"]()
        self.execute_cell(6)
        self.assertEqual(self.status(paper_id)["status"], "error")
        self.assertFalse((self.root / "escaped.tex").exists())
        self.assertFalse((self.version_dir(paper_id).parent / "done.json").exists())

    def test_tar_absolute_names_are_recorded_relative_to_version_directory(self):
        paper_id = "2508.00001v1"
        self.configure([paper_id])
        self.mock_source(lambda _: self.archive({"/nested/main.tex": b"Text."}))
        self.namespace["crawl_sources"]()
        self.execute_cell(6)
        self.assertEqual(self.status(paper_id)["files"], ["nested/main.tex"])
        self.assertEqual((self.version_dir(paper_id) / "nested/main.tex").read_bytes(), b"Text.")
        self.assertEqual(self.status(paper_id)["status"], "ok")

    def test_failed_redownload_invalidates_done_and_does_not_extract_old_archive(self):
        paper_id = "2508.00001v1"
        self.configure([paper_id])
        self.mock_source(lambda _: gzip.compress(b"\\documentclass{article}"))
        self.namespace["crawl_sources"]()
        self.execute_cell(6)
        done_path = self.version_dir(paper_id).parent / "done.json"
        self.assertTrue(done_path.exists())

        def fetch(_):
            raise HTTPError("https://export.arxiv.org/src/example", 404, "Missing", {}, None)

        self.mock_source(fetch)
        self.namespace["crawl_sources"]()
        self.assertFalse(done_path.exists())
        self.execute_cell(6)
        self.assertEqual(self.status(paper_id)["status"], "error")
        self.assertFalse(done_path.exists())

    def test_id_slice_and_metadata_append_behavior_are_preserved(self):
        ids = [f"2508.{index:05d}v1" for index in range(4)]
        self.configure(ids)
        self.namespace.update(START_IDX=1, END_IDX=3)
        self.assertEqual(self.namespace["get_id_list"](), ids[1:3])
        old = {"id": "2409.00001v1", "path": "old.tar.gz", "state": "success"}
        self.metadata.write_text(json.dumps([old]))
        self.mock_source(lambda _: b"%PDF-1.4")
        self.namespace["crawl_sources"]()
        self.assertEqual(json.loads(self.metadata.read_text())[0], old)
        self.namespace["crawl_sources"]()
        self.assertEqual(len(json.loads(self.metadata.read_text())), 1 + 2 * len(ids))


if __name__ == "__main__":
    unittest.main()
