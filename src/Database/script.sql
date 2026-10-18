CREATE TABLE PAPERS (
    arxiv_id TEXT PRIMARY KEY,
    title TEXT,
    authors TEXT,
    submission_date DATE,
    revised_date DATE,
    venue DATE,
    content TEXT
);

CREATE TABLE PAPER_REFERENCES
(
    arxiv_id            TEXT,
    ref_arxiv_id        TEXT,
    ref_title           TEXT,
    ref_authors         TEXT,
    ref_submission_date DATE,
    ref_s2_id           TEXT,

    PRIMARY KEY (arxiv_id, ref_arxiv_id),

    FOREIGN KEY (arxiv_id) REFERENCES PAPERS (arxiv_id)
);