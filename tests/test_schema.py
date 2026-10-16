"""Regression tests cho hợp đồng Crawling và tính an toàn của Parquet I/O.

Chạy cả bộ: python3 -m pytest -q
Không cần mạng, token hoặc dữ liệu arXiv thật.
"""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pyarrow as pa

from src.common import schema as s


def paper(**updates):
    """Bản ghi tổng hợp, cố ý có dấu phân cách trong tên tác giả."""
    record = {
        "arxiv_id": "2508.02872",
        "title": "Synthetic paper",
        "authors": ["Group; Collaboration", "Nguyễn Thành Bảo"],
        "submission_date": "2025-08-04T12:30:00Z",
        "revised_dates": ["2025-09-01", "2025-10-01T10:00:00+07:00"],
        "venue": None,
    }
    return record | updates


class SchemaTests(unittest.TestCase):
    def test_empty_tables(self):
        for name in s.SCHEMAS:
            with self.subTest(name=name):
                self.assertEqual(s.validate(s.empty_table(name), name), [])

    def test_crawling_lists(self):
        table = s.from_records([paper()], "papers")
        self.assertEqual(table["authors"].type, pa.list_(pa.string()))
        self.assertEqual(table.to_pylist()[0]["authors"], paper()["authors"])
        refs = s.from_records([{
            "arxiv_id": "2508.02872", "ref_arxiv_id": "hep-th/9901001",
            "ref_authors": ["Author A", "Author B"],
        }], "references")
        self.assertEqual(refs["ref_authors"].type, pa.list_(pa.string()))

    def test_empty_list_and_unknown_list_remain_distinct(self):
        for value in ([], None):
            with self.subTest(value=value):
                table = s.from_records([paper(revised_dates=value)], "papers")
                self.assertEqual(table.to_pylist()[0]["revised_dates"], value)

    def test_missing_and_wrong_type_columns(self):
        table = s.from_records([paper()], "papers")
        self.assertIn("thiếu cột", "\n".join(s.validate(table.drop(["title"]), "papers")))
        index = table.schema.get_field_index("authors")
        wrong = table.set_column(index, "authors", pa.array(["A; B"]))
        self.assertIn("kiểu", "\n".join(s.validate(wrong, "papers")))

    def test_extra_and_duplicate_columns(self):
        table = s.from_records([paper()], "papers")
        extra = table.append_column("unexpected", pa.array(["x"]))
        duplicate = table.append_column("title", pa.array(["x"]))
        self.assertIn("thừa cột", "\n".join(s.validate(extra, "papers")))
        self.assertIn("tên cột trùng", "\n".join(s.validate(duplicate, "papers")))

    def test_unrecognized_record_field_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "titel"):
            s.from_records([paper(titel="Mistyped title")], "papers")

    def test_invalid_dates_rejected_including_later_list_items(self):
        cases = [
            {"submission_date": "2025-02-30"},
            {"submission_date": "2025-08-04garbage"},
            {"submission_date": "2025-08-04T25:00:00Z"},
            {"revised_dates": ["2025-09-01", "not a date"]},
            {"revised_dates": ["2025-09-01", "2025-99-99"]},
        ]
        for updates in cases:
            with self.subTest(updates=updates), self.assertRaisesRegex(ValueError, "ngày ISO"):
                s.from_records([paper(**updates)], "papers")

    def test_reference_date_is_checked(self):
        with self.assertRaisesRegex(ValueError, "ref_submission_date"):
            s.from_records([{
                "arxiv_id": "2508.02872", "ref_arxiv_id": "hep-th/9901001",
                "ref_submission_date": "2025-02-29",
            }], "references")

    def test_null_key_and_duplicate_keys_rejected(self):
        with self.assertRaisesRegex(ValueError, "null"):
            s.from_records([paper(arxiv_id=None)], "papers")
        with self.assertRaisesRegex(ValueError, "bị trùng"):
            s.from_records([paper(), paper()], "papers")

    def test_publication_id_must_not_include_version(self):
        with self.assertRaisesRegex(ValueError, "sai định dạng"):
            s.from_records([paper(arxiv_id="2508.02872v1")], "papers")

    def test_parquet_round_trip_in_partition_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "owner=bao" / "papers.parquet"
            table = s.from_records([paper()], "papers")
            s.write_table(table, "papers", path)
            self.assertTrue(s.read_table("papers", path).equals(table))

    def test_failed_write_preserves_previous_file_and_cleans_temp(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "papers.parquet"
            before = s.from_records([paper()], "papers")
            after = s.from_records([paper(title="Replacement")], "papers")
            s.write_table(before, "papers", path)

            def fail_write(table, stream, **kwargs):
                stream.write(b"partial parquet")
                raise OSError("simulated disk failure")

            with patch.object(s.pq, "write_table", side_effect=fail_write):
                with self.assertRaisesRegex(OSError, "simulated"):
                    s.write_table(after, "papers", path)
            self.assertTrue(s.read_table("papers", path).equals(before))
            self.assertEqual(list(Path(directory).iterdir()), [path])
            s.write_table(after, "papers", path)
            self.assertTrue(s.read_table("papers", path).equals(after))

    def test_invalid_write_does_not_touch_destination(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "papers.parquet"
            path.write_bytes(b"original")
            invalid = pa.Table.from_pylist([paper(arxiv_id=None)], schema=s.SCHEMAS["papers"])
            with self.assertRaises(ValueError):
                s.write_table(invalid, "papers", path)
            self.assertEqual(path.read_bytes(), b"original")

    def test_legacy_join_refuses_lossy_strings(self):
        for items in (["Group; Collaboration", "B"], [""]):
            with self.subTest(items=items), self.assertRaises(ValueError):
                s.join_list(items)
        self.assertEqual(s.split_list(s.join_list(["A", "B"])), ["A", "B"])


if __name__ == "__main__":
    unittest.main()
