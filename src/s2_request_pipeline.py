import os
import asyncio
import json
import sqlite3
from pathlib import Path

import aiohttp
from dotenv import load_dotenv
from src.s2_request import S2_Request

SRC_DIR = Path(__file__).resolve().parent
DB_PATH = SRC_DIR / "Database" / "data.sqlite3"
METADATA_DIR = SRC_DIR / "data" / "s2_references"
load_dotenv(SRC_DIR.parent / ".env")

crawler1 = S2_Request(os.getenv("S2_API_KEY1"))
crawler2 = S2_Request(os.getenv("S2_API_KEY2"))
crawler3 = S2_Request(os.getenv("S2_API_KEY3"))

crawlers = [crawler1, crawler2, crawler3]
ref_ids = []  # Tự thêm ID; để trống thì lấy từ bảng PAPERS.


async def crawl_worker(crawler, assigned_ids, results, db):
    for paper_id in assigned_ids:
        try:
            data = await crawler.send_async_request(paper_id)

            metadata_path = METADATA_DIR / f"{paper_id.replace('/', '_')}.json"
            with metadata_path.open("w", encoding="utf-8") as file:
                json.dump(data, file, ensure_ascii=False, indent=2)

            version = db.execute(
                "SELECT version FROM PAPERS WHERE arxiv_id = ? ORDER BY revised_date DESC LIMIT 1",
                (paper_id,),
            ).fetchone()[0]
            with db:
                for reference in data["references"]:
                    if not reference:
                        continue
                    ref_arxiv_id = (reference.get("externalIds") or {}).get("ArXiv")
                    if not ref_arxiv_id:
                        continue
                    authors = reference.get("authors")
                    if authors is not None:
                        authors = json.dumps([author["name"] for author in authors], ensure_ascii=False)
                    submission_date = db.execute(
                        "SELECT submission_date FROM PAPERS WHERE arxiv_id = ? LIMIT 1",
                        (ref_arxiv_id,),
                    ).fetchone()
                    db.execute(
                        """
                        INSERT INTO PAPER_REFERENCES (
                            arxiv_id, version, ref_arxiv_id, ref_title, ref_authors,
                            ref_submission_date, ref_s2_id
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT (arxiv_id, ref_arxiv_id) DO NOTHING
                        """,
                        (paper_id, version, ref_arxiv_id, reference.get("title"), authors,
                         submission_date[0] if submission_date else None, reference.get("paperId")),
                    )

            results[paper_id] = data
            print(f"[OK] {paper_id}")
        except (aiohttp.ClientError, asyncio.TimeoutError) as error:
            print(f"[ERROR] {paper_id}: {type(error).__name__}")
            results[paper_id] = None


async def main():
    db = sqlite3.connect(DB_PATH.resolve().as_uri() + "?mode=rw", uri=True)
    try:
        db.execute("PRAGMA foreign_keys = ON")
        paper_ids = ref_ids or [
            row[0] for row in db.execute("SELECT DISTINCT arxiv_id FROM PAPERS")
        ]
        METADATA_DIR.mkdir(parents=True, exist_ok=True)
        results = {}
        tasks = [
            crawl_worker(
                crawler,
                paper_ids[i::len(crawlers)],
                results,
                db,
            )
            for i, crawler in enumerate(crawlers)
        ]
        await asyncio.gather(*tasks)
        return results
    finally:
        db.close()


if __name__ == "__main__":
    results = asyncio.run(main())
