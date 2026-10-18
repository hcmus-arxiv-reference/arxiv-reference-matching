import json
import sqlite3


def _decode_author_lists(cursor, row):
    return tuple(
        json.loads(value)
        if column[0] in {"authors", "ref_authors"} and value is not None
        else value
        for column, value in zip(cursor.description, row)
    )


class SQLite:
    def __init__(self):
        self.conn = sqlite3.connect("./data.sqlite3")
        self.conn.row_factory = _decode_author_lists
        self.cursor = self.conn.cursor()


    def init_table(self):
        script = """
            CREATE TABLE PAPERS (
                arxiv_id TEXT,
                version TEXT, 
                title TEXT,
                authors TEXT,
                submission_date DATE,
                revised_date DATE,
                venue DATE,
                content TEXT,
                PRIMARY KEY  (arxiv_id, version)
            );
    
            CREATE TABLE PAPER_REFERENCES (
                arxiv_id TEXT,
                version TEXT,
                ref_arxiv_id TEXT,
                ref_title TEXT,
                ref_authors TEXT,
                ref_submission_date DATE,
                ref_s2_id TEXT,
                
                PRIMARY KEY (arxiv_id, ref_arxiv_id), 
                FOREIGN KEY (arxiv_id, version) REFERENCES PAPERS(arxiv_id, version)
            )
        """

        self.cursor.executescript(script)
        return 200

    def insert_paper(
        self, arxiv_id, title, authors, submission_date, revised_date=None, venue=None
    ):
        authors = json.dumps(authors, ensure_ascii=False) if authors is not None else None
        self.cursor.execute(
            """
            INSERT INTO PAPERS (
                arxiv_id, title, authors, submission_date, revised_date, venue
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (arxiv_id, title, authors, submission_date, revised_date, venue),
        )
        self.conn.commit()
        return 200

    def insert_reference(
        self, arxiv_id, ref_arxiv_id, ref_title, ref_authors,
        ref_submission_date=None, ref_s2_id=None
    ):
        ref_authors = json.dumps(ref_authors, ensure_ascii=False) if ref_authors is not None else None
        self.cursor.execute(
            """
            INSERT INTO PAPER_REFERENCES (
                arxiv_id, ref_arxiv_id, ref_title, ref_authors,
                ref_submission_date, ref_s2_id
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (arxiv_id, ref_arxiv_id, ref_title, ref_authors,
             ref_submission_date, ref_s2_id),
        )
        self.conn.commit()
        return 200

    def get_papers(self):
        self.cursor.execute("SELECT * FROM PAPERS")
        return self.cursor.fetchall()

    def get_paper(self, arxiv_id):
        self.cursor.execute(
            "SELECT * FROM PAPERS WHERE arxiv_id = ?", (arxiv_id,)
        )
        return self.cursor.fetchone()

    def get_references(self, arxiv_id):
        self.cursor.execute(
            "SELECT * FROM PAPER_REFERENCES WHERE arxiv_id = ?", (arxiv_id,)
        )
        return self.cursor.fetchall()

    def get_reference(self, arxiv_id, ref_arxiv_id):
        self.cursor.execute(
            "SELECT * FROM PAPER_REFERENCES WHERE arxiv_id = ? AND ref_arxiv_id = ?",
            (arxiv_id, ref_arxiv_id),
        )
        return self.cursor.fetchone()


if __name__ == "__main__":
    sql = SQLite()
    sql.init_table()