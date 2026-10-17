import sqlite3


class SQLite:
    def __init__(self):
        self.conn = sqlite3.connect("data.sqlite3")
        self.cursor = self.conn.cursor()


    def init_table(self):
        script = """
            CREATE TABLE PAPERS (
                arxiv_id TEXT PRIMARY KEY,
                title TEXT,
                authors TEXT,
                submission_date DATE,
                revised_date DATE,
                venue DATE
            );
    
            CREATE TABLE PAPER_REFERENCES (
                arxiv_id TEXT,
                ref_arxiv_id TEXT,
                ref_title TEXT,
                ref_authors TEXT,
                ref_submission_date DATE,
                ref_s2_id TEXT,
                
                PRIMARY KEY (arxiv_id, ref_arxiv_id), 
                FOREIGN KEY (arxiv_id) REFERENCES PAPERS(arxiv_id)
            )
        """

        self.cursor.executescript(script)
        return 200

    def insert_paper(
        self, arxiv_id, title, authors, submission_date, revised_date=None, venue=None
    ):
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