"""Focused tests for metadata insertion and SQLite author lists."""

import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from src import insert_to_db
from src.Database.sql_db import SQLite


class InsertMetadataTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.db_path = self.root / "test.sqlite3"
        self.json_path = self.root / "metadata.json"
        connection = sqlite3.connect(self.db_path)
        with patch("src.Database.sql_db.sqlite3.connect", return_value=connection):
            self.db = SQLite()
        self.addCleanup(connection.close)
        self.db.init_table()
        self.paper = {
            "arxiv_id": "2409.18594",
            "latest_version": "2409.18594v2",
            "versions": ["2409.18594v1", "2409.18594v2"],
            "title": "A paper's title",
            "authors": ["Nguyễn Văn A", "Group; B"],
            "published": "2024-09-27T09:53:48Z",
            "updated": "2025-05-27T09:01:46Z",
            "journal_ref": "Example journal",
            "summary": "An abstract, not full LaTeX content",
        }

    def write_input(self, papers):
        self.json_path.write_text(
            json.dumps({"papers": papers}, ensure_ascii=False), encoding="utf-8"
        )

    def test_metadata_mapping_and_list_authors(self):
        self.write_input([self.paper])
        self.assertEqual(insert_to_db.insert_metadata(self.json_path, self.db_path), 1)
        row = self.db.get_paper("2409.18594")
        self.assertEqual(row[:3], ("2409.18594", "2409.18594v2", "A paper's title"))
        self.assertEqual(row[3], self.paper["authors"])
        self.assertEqual(row[4:7], (
            self.paper["published"], self.paper["updated"], "Example journal"
        ))
        self.assertIsNone(row[7])
        self.assertEqual(self.db.get_papers(), [row])
        with sqlite3.connect(self.db_path) as connection:
            self.assertEqual(connection.execute(
                "SELECT typeof(authors), json_type(authors) FROM PAPERS"
            ).fetchone(), ("text", "array"))

    def test_rerun_preserves_existing_title_and_content(self):
        self.write_input([self.paper])
        insert_to_db.insert_metadata(self.json_path, self.db_path)
        with self.db.conn:
            self.db.conn.execute(
                "UPDATE PAPERS SET title = 'existing title', content = 'existing TeX'"
            )
        self.assertEqual(insert_to_db.insert_metadata(self.json_path, self.db_path), 0)
        row = self.db.get_paper("2409.18594")
        self.assertEqual((row[2], row[7]), ("existing title", "existing TeX"))
        self.assertEqual(len(self.db.get_papers()), 1)

    def test_first_version_has_no_revision_date(self):
        self.write_input([dict(self.paper, latest_version="2409.18594v1", journal_ref=None)])
        insert_to_db.insert_metadata(self.json_path, self.db_path)
        row = self.db.get_paper("2409.18594")
        self.assertIsNone(row[5])
        self.assertIsNone(row[6])

    def test_invalid_later_record_rolls_back_entire_import(self):
        invalid = dict(self.paper, arxiv_id="2409.18595", latest_version="2409.18595v1")
        del invalid["title"]
        self.write_input([self.paper, invalid])
        with self.assertRaises(KeyError):
            insert_to_db.insert_metadata(self.json_path, self.db_path)
        self.assertEqual(self.db.get_papers(), [])

    def test_missing_database_is_not_silently_created(self):
        self.write_input([self.paper])
        missing = self.root / "missing.sqlite3"
        with self.assertRaises(sqlite3.OperationalError):
            insert_to_db.insert_metadata(self.json_path, missing)
        self.assertFalse(missing.exists())

    def test_insert_paper_and_reference_round_trip_author_lists(self):
        authors = ["Nguyễn Văn A", "Group; B"]
        self.db.insert_paper("2409.18594", "Title", authors, "2024-09-27")
        self.db.insert_reference("2409.18594", "2301.00001", "Reference", authors)
        self.assertEqual(self.db.get_paper("2409.18594")[3], authors)
        reference = self.db.get_reference("2409.18594", "2301.00001")
        self.assertEqual(reference[4], authors)
        self.assertEqual(self.db.get_references("2409.18594"), [reference])

    def test_empty_and_null_author_lists_remain_distinct(self):
        for index, authors in enumerate(([], None)):
            with self.subTest(authors=authors):
                arxiv_id = f"2409.{index:05d}"
                self.db.insert_paper(arxiv_id, "Title", authors, "2024-09-27")
                self.db.insert_reference(arxiv_id, "2301.00001", "Reference", authors)
                self.assertEqual(self.db.get_paper(arxiv_id)[3], authors)
                self.assertEqual(self.db.get_reference(arxiv_id, "2301.00001")[4], authors)

    def test_missing_records_preserve_existing_return_values(self):
        self.assertIsNone(self.db.get_paper("missing"))
        self.assertIsNone(self.db.get_reference("missing", "missing"))
        self.assertEqual(self.db.get_references("missing"), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
