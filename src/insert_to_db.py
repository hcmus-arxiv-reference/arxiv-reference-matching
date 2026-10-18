"""Insert latest-version arXiv metadata into the existing SQLite PAPERS table."""

import argparse
from contextlib import closing
import json
from pathlib import Path
import sqlite3


SRC_DIR = Path(__file__).resolve().parent
JSON_PATH = SRC_DIR / "data" / "arxiv_metadata.json"
DB_PATH = SRC_DIR / "Database" / "data.sqlite3"


def insert_metadata(json_path=JSON_PATH, db_path=DB_PATH):
    """Return the number of new rows, preserving existing paper records."""
    with Path(json_path).open(encoding="utf-8") as file:
        papers = json.load(file)["papers"]

    # mode=rw avoids silently creating an empty database at the wrong path.
    db_uri = Path(db_path).resolve().as_uri() + "?mode=rw"
    with closing(sqlite3.connect(db_uri, uri=True)) as connection:
        with connection:
            before = connection.total_changes
            connection.executemany(
                """
                INSERT INTO PAPERS (
                    arxiv_id, version, title, authors,
                    submission_date, revised_date, venue
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (arxiv_id, version) DO NOTHING
                """,
                (
                    (
                        paper["arxiv_id"],
                        paper["latest_version"],
                        paper["title"],
                        json.dumps(paper["authors"], ensure_ascii=False),
                        paper["published"],
                        paper["updated"]
                        if paper["latest_version"] != paper["arxiv_id"] + "v1"
                        else None,
                        paper.get("journal_ref"),
                    )
                    for paper in papers
                ),
            )
        return connection.total_changes - before


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", type=Path, default=JSON_PATH)
    parser.add_argument("--db", type=Path, default=DB_PATH)
    args = parser.parse_args()
    inserted = insert_metadata(args.json, args.db)
    print(f"Đã thêm {inserted} bản ghi mới vào PAPERS: {args.db}")


if __name__ == "__main__":
    main()
