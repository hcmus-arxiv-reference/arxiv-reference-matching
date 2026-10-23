"""SQLite working store; published Parquet schemas remain unchanged."""
import json
import sqlite3
from pathlib import Path


class Store:
    """One writer, transactional checkpoints; close before moving the workspace."""
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS metadata (
          cache_key TEXT PRIMARY KEY, arxiv_id TEXT, version INTEGER, title TEXT,
          submission_date TEXT, updated TEXT, venue TEXT, abstract TEXT);
        CREATE TABLE IF NOT EXISTS authors (
          cache_key TEXT, position INTEGER, name TEXT, PRIMARY KEY(cache_key, position));
        CREATE TABLE IF NOT EXISTS versions (
          arxiv_id TEXT, version INTEGER, status TEXT, error TEXT, download_bytes INTEGER,
          kept_bytes INTEGER, download_seconds REAL, extract_seconds REAL,
          PRIMARY KEY(arxiv_id, version));
        CREATE TABLE IF NOT EXISTS files (
          arxiv_id TEXT, version INTEGER, path TEXT, sha256 TEXT,
          PRIMARY KEY(arxiv_id, version, path));
        CREATE TABLE IF NOT EXISTS reference_jobs (
          arxiv_id TEXT PRIMARY KEY, status TEXT, next_offset INTEGER DEFAULT 0,
          attempts INTEGER DEFAULT 0, error TEXT);
        CREATE TABLE IF NOT EXISTS s2_references (
          arxiv_id TEXT, position INTEGER, s2_id TEXT, ref_arxiv_id TEXT,
          title TEXT, publication_date TEXT, PRIMARY KEY(arxiv_id, position));
        CREATE TABLE IF NOT EXISTS reference_authors (
          arxiv_id TEXT, reference_position INTEGER, position INTEGER, name TEXT,
          PRIMARY KEY(arxiv_id, reference_position, position));
        CREATE TABLE IF NOT EXISTS runs (
          id INTEGER PRIMARY KEY, started TEXT DEFAULT CURRENT_TIMESTAMP,
          status TEXT, wall_seconds REAL, arxiv_requests INTEGER, s2_requests INTEGER);
        CREATE TABLE IF NOT EXISTS run_errors (
          run_id INTEGER, message TEXT);
        ''')

    def get_metadata(self, key):
        row = self.db.execute('SELECT * FROM metadata WHERE cache_key=?', (key,)).fetchone()
        if row is None:
            return None
        result = dict(row)
        result.pop('cache_key')
        result['authors'] = [r[0] for r in self.db.execute(
            'SELECT name FROM authors WHERE cache_key=? ORDER BY position', (key,))]
        return result

    def put_metadata(self, key, value):
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO metadata VALUES (?,?,?,?,?,?,?,?)',
                (key, *(value.get(k) for k in ('arxiv_id', 'version', 'title', 'submission_date', 'updated', 'venue', 'abstract'))))
            self.db.execute('DELETE FROM authors WHERE cache_key=?', (key,))
            self.db.executemany('INSERT INTO authors VALUES (?,?,?)',
                [(key, i, name) for i, name in enumerate(value.get('authors') or [])])

    def get_version(self, identifier, version):
        row = self.db.execute('SELECT * FROM versions WHERE arxiv_id=? AND version=?', (identifier, version)).fetchone()
        if row is None:
            return None
        result = dict(row)
        result['files'] = dict(self.db.execute('SELECT path,sha256 FROM files WHERE arxiv_id=? AND version=?', (identifier, version)))
        return result

    def put_version(self, value):
        keys = ('arxiv_id', 'version', 'status', 'error', 'download_bytes', 'kept_bytes', 'download_seconds', 'extract_seconds')
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO versions VALUES (?,?,?,?,?,?,?,?)', tuple(value.get(k) for k in keys))
            pair = (value['arxiv_id'], value['version'])
            self.db.execute('DELETE FROM files WHERE arxiv_id=? AND version=?', pair)
            self.db.executemany('INSERT INTO files VALUES (?,?,?,?)', [(*pair, p, h) for p, h in value['files'].items()])

    def import_legacy(self, root):
        """Import existing JSON only when absent in SQL; source stays in place."""
        root = Path(root)
        for path in root.glob('*/metadata/*.json'):
            if self.get_metadata(path.stem) is None:
                self.put_metadata(path.stem, json.loads(path.read_text(encoding='utf-8')))
        for path in root.glob('*/v*/checkpoint.json'):
            value = json.loads(path.read_text(encoding='utf-8'))
            if self.get_version(value['arxiv_id'], value['version']) is None:
                self.put_version(value)

    def backup(self, path):
        """Consistent SQLite snapshot, including committed transactions."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.resolve() == self.path.resolve():
            raise ValueError('Backup path must differ from database')
        target = sqlite3.connect(path)
        try:
            self.db.backup(target)
        finally:
            target.close()

    def close(self):
        self.db.close()
