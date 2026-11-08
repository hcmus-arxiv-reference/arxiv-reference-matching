import contextlib
import csv
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

NOTEBOOK = Path(__file__).resolve().parents[1] / "src/merge_arxiv_kaggle.ipynb"


class MergeArxivNotebookTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.notebook = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
        self.namespace = {}
        for cell in self.notebook["cells"]:
            if cell["cell_type"] == "code" and cell["metadata"].get("tags"):
                exec(compile("".join(cell["source"]), str(NOTEBOOK), "exec"), self.namespace)
        self.ids = ["2409.99998v1", "2409.99998v2", "2410.00001v1"]
        self.roots = {}
        for part in (1, 2, 3):
            mount = self.root / "input" / f"part{part}"
            crawl = mount / f"arxiv-part{part}"
            (crawl / "output").mkdir(parents=True)
            (mount / "arxiv_id.txt").write_text("\n".join(self.ids) + "\n")
            (crawl / "metadata.json").write_text("[]")
            self.roots[part] = crawl
        self.logs = io.StringIO()
        self.enterContext(contextlib.redirect_stdout(self.logs))

    def put(self, part, relative, content):
        target = self.roots[part] / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        return target

    def version(self, part, version_id, status="ok"):
        _, version, directory = self.namespace["version_location"](version_id)
        archive = f"output/{version_id}.tar.gz"
        self.put(part, archive, b"synthetic compressed archive\x00" + version_id.encode())
        names = ["nested/main.tex", "refs.bib"] if status == "ok" else []
        for name in names:
            self.put(part, f"{directory}/{name}", b"synthetic source\x00\xff" + name.encode())
        record = {"version": version, "kind": "tar", "status": status, "files": names,
                  "bytes_downloaded": 10, "bytes_before": 100, "bytes_after": 20,
                  "seconds": 1.25}
        self.put(part, f"{directory}/status.json", json.dumps(record).encode())
        metadata_path = self.roots[part] / "metadata.json"
        rows = json.loads(metadata_path.read_text())
        rows.append({"id": version_id, "path": f"/kaggle/working/arxiv-part{part}/{archive}",
                     "state": "success"})
        metadata_path.write_text(json.dumps(rows))
        return record

    def plan(self):
        return self.namespace["build_merge_plan"](self.roots, len(self.ids), self.root / "work")

    def populate(self):
        for part, version_id in enumerate(self.ids, 1):
            self.version(part, version_id, "empty" if part == 3 else "ok")

    def test_notebook_format_and_all_code_cells_compile(self):
        self.assertEqual(self.notebook["nbformat"], 4)
        for cell in self.notebook["cells"]:
            if cell["cell_type"] == "code":
                compile("".join(cell["source"]), str(NOTEBOOK), "exec")
                self.assertIsNone(cell["execution_count"])
                self.assertEqual(cell["outputs"], [])

    def test_merge_preserves_bytes_retries_and_rebuilds_cross_part_done(self):
        self.populate()
        original_done = b'{"id":"2409.99998","n_versions":1,"status":"done"}'
        self.put(1, "output/2409-99998/done.json", original_done)
        self.put(1, "output/pass.txt", b"stale-id\n")
        metadata_path = self.roots[1] / "metadata.json"
        success = json.loads(metadata_path.read_text())[0]
        failed = {**success, "state": "fail"}
        metadata_path.write_text(json.dumps([failed, success]))
        original_metadata = metadata_path.read_bytes()
        # A successful source may itself contain a file called done.json.
        self.put(1, "output/2409-99998/v1/done.json", b"auxiliary file")
        files, fingerprints, generated, report = self.plan()
        self.assertTrue(report["crawl_complete_for_expected_ids"])
        self.assertEqual(report["expected_publications"], 2)
        self.assertEqual(report["version_status_counts"], {"ok": 2, "empty": 1})
        done = json.loads(generated["output/2409-99998/done.json"])
        self.assertEqual(done["n_versions"], 2)
        self.assertEqual(done["bytes_downloaded"], 20)
        self.assertEqual(done["seconds"], 2.5)
        rows = json.loads(generated["metadata.json"])
        self.assertEqual([r["state"] for r in rows], ["fail", "success", "success", "success"])
        self.assertEqual(set(rows[0]), {"id", "path", "state"})
        self.assertEqual(rows[0]["path"], f"output/{self.ids[0]}.tar.gz")
        self.assertEqual(generated["output/pass.txt"], b"2410.00001v1\n")
        zip_path = self.root / "work" / "merged.zip"
        checksum = self.namespace["write_merge_zip"](zip_path, files, fingerprints, generated)
        with zipfile.ZipFile(zip_path) as archive:
            self.assertIsNone(archive.testzip())
            self.assertEqual(archive.read("arxiv-merged/provenance/part1/metadata.json"), original_metadata)
            self.assertEqual(archive.read("arxiv-merged/provenance/part1/output/2409-99998/done.json"), original_done)
            self.assertIn("arxiv-merged/output/2410-00001/v1/status.json", archive.namelist())
            self.assertIn("arxiv-merged/output/2409-99998/v1/done.json", archive.namelist())
            checks = list(csv.DictReader(io.StringIO(archive.read("arxiv-merged/checksums.csv").decode())))
            self.assertEqual(len(checks), len(archive.namelist()) - 1)
            for row in checks:
                payload = archive.read("arxiv-merged/" + row["path"])
                self.assertEqual(hashlib.sha256(payload).hexdigest(), row["sha256"])
                self.assertEqual(len(payload), int(row["bytes"]))
            for name, source in files.items():
                self.assertEqual(archive.read("arxiv-merged/" + name), source.read_bytes())
        self.assertEqual(checksum.read_text().split()[0], hashlib.sha256(zip_path.read_bytes()).hexdigest())
        self.assertEqual(metadata_path.read_bytes(), original_metadata)

    def test_missing_version_and_declared_file_are_reported_not_marked_done(self):
        self.version(1, self.ids[0])
        self.version(2, self.ids[1])
        (self.roots[2] / "output/2409-99998/v2/nested/main.tex").unlink()
        _, _, generated, report = self.plan()
        self.assertFalse(report["crawl_complete_for_expected_ids"])
        self.assertNotIn("output/2409-99998/done.json", generated)
        versions = {row["id"]: row for row in json.loads(generated["reports/versions.json"])}
        self.assertIn("nested/main.tex", versions[self.ids[1]]["issues"])
        self.assertEqual(versions[self.ids[2]]["status"], "missing")
        self.assertEqual(report["incomplete_versions"], 2)

    def test_empty_and_error_remain_distinct_and_missing_archive_is_detected(self):
        self.populate()
        self.version(2, "2410.00002v1", status="error")
        (self.roots[3] / "output/2410.00001v1.tar.gz").unlink()
        _, _, generated, report = self.plan()
        self.assertEqual(report["unexpected_metadata_ids"], ["2410.00002v1"])
        self.assertEqual(report["version_status_counts"]["error"], 1)
        self.assertNotIn("output/2410-00001/done.json", generated)
        versions = {row["id"]: row for row in json.loads(generated["reports/versions.json"])}
        self.assertIn("archive .tar.gz", versions[self.ids[2]]["issues"])

    def test_identical_file_collision_is_deduplicated(self):
        self.populate()
        self.put(1, "output/shared.txt", b"same")
        self.put(2, "output/shared.txt", b"same")
        files, _, _, report = self.plan()
        self.assertIn("output/shared.txt", files)
        self.assertEqual(report["identical_duplicate_files"], 1)

    def test_different_file_collision_stops_before_zip(self):
        self.populate()
        self.put(1, "output/shared.txt", b"first")
        self.put(2, "output/shared.txt", b"other")
        with self.assertRaisesRegex(ValueError, "khác nội dung"):
            self.plan()
        conflicts = json.loads((self.root / "work/merge-conflicts.json").read_text())
        self.assertEqual(conflicts[0]["path"], "output/shared.txt")
        self.assertEqual(list((self.root / "work").glob("*.zip")), [])

    def test_discovery_requires_three_distinct_sources(self):
        discover = self.namespace["discover_sources"]
        roots = discover(self.root / "input", {})
        self.assertEqual(roots, self.roots)
        with self.assertRaisesRegex(ValueError, "cùng một thư mục"):
            discover(self.root / "input", {part: self.roots[1] for part in (1, 2, 3)})
        self.roots[3].rename(self.roots[3].with_name("unexpected"))
        with self.assertRaisesRegex(ValueError, "Part 3"):
            discover(self.root / "input", {})

    def test_expected_lists_must_agree_and_count_is_checked(self):
        self.populate()
        path = self.roots[3].parent / "arxiv_id.txt"
        original = path.read_text()
        path.write_text(self.ids[0])
        with self.assertRaisesRegex(ValueError, "khác các part trước"):
            self.plan()
        path.write_text(original)
        with self.assertRaisesRegex(ValueError, "cấu hình yêu cầu"):
            self.namespace["build_merge_plan"](self.roots, 100, self.root / "work")

    def test_discovery_does_not_descend_into_source_trees(self):
        nested = self.roots[1] / "output/auxiliary/arxiv-part1"
        (nested / "output").mkdir(parents=True)
        (nested / "metadata.json").write_text("[]")
        self.assertEqual(self.namespace["discover_sources"](self.root / "input", {}), self.roots)

    def test_rerun_never_overwrites_existing_zip_or_partial(self):
        self.populate()
        files, fingerprints, generated, _ = self.plan()
        target = self.root / "work" / "merged.zip"
        target.write_bytes(b"existing output")
        with self.assertRaises(FileExistsError):
            self.namespace["write_merge_zip"](target, files, fingerprints, generated)
        self.assertEqual(target.read_bytes(), b"existing output")
        other = self.root / "work" / "other.zip"
        other.with_suffix(".zip.partial").write_bytes(b"interrupted")
        with self.assertRaises(FileExistsError):
            self.namespace["write_merge_zip"](other, files, fingerprints, generated)

    def test_changed_source_is_detected_and_zip_is_not_published(self):
        self.populate()
        files, fingerprints, generated, _ = self.plan()
        next(iter(files.values())).write_bytes(b"changed after planning")
        target = self.root / "work" / "merged.zip"
        with self.assertRaisesRegex(ValueError, "thay đổi"):
            self.namespace["write_merge_zip"](target, files, fingerprints, generated)
        self.assertFalse(target.exists())

    def test_full_notebook_runs_with_synthetic_inputs_and_no_network(self):
        self.populate()
        namespace = {}
        with patch("socket.socket.connect", side_effect=AssertionError("Network is forbidden")):
            for cell in self.notebook["cells"]:
                if cell["cell_type"] != "code":
                    continue
                exec(compile("".join(cell["source"]), str(NOTEBOOK), "exec"), namespace)
                if "configuration" in cell["metadata"].get("tags", []):
                    namespace.update(INPUT_DIR=self.root / "input", WORK_DIR=self.root / "work",
                                     ZIP_PATH=self.root / "work" / "merged.zip",
                                     EXPECTED_VERSION_COUNT=len(self.ids))
        self.assertTrue(namespace["ZIP_PATH"].is_file())
        self.assertTrue(namespace["report"]["crawl_complete_for_expected_ids"])


if __name__ == "__main__":
    unittest.main()
