"""Generate notebook and code-only ZIP for Kaggle; never include .env or data."""
import json
from pathlib import Path
import zipfile


def main():
    root = Path(__file__).resolve().parents[1]
    output = root / 'outputs'
    output.mkdir(exist_ok=True)
    with zipfile.ZipFile(output / 'arxiv_crawler_code.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in sorted((root / 'src').rglob('*.py')):
            archive.write(path, path.relative_to(root).as_posix())
    cells = []
    def md(text):
        cells.append(dict(cell_type='markdown', metadata={}, source=text.splitlines(True)))
    def code(text):
        cells.append(dict(cell_type='code', metadata={}, source=text.splitlines(True), outputs=[], execution_count=None))
    md('''# arXiv M1: VS Code / Kaggle + SQLite + Semantic Scholar
VS Code: open this repo, select a Python kernel, put CONTACT_EMAIL and S2_API_KEY
in the root .env, then Restart Kernel and run cells in order. No ZIP is needed locally.

Kaggle:
Upload `arxiv_crawler_code.zip` as a private Kaggle Dataset, then Add Input.
Enable Internet; CPU is sufficient. Add Secrets `CONTACT_EMAIL` and `S2_API_KEY`
and enable notebook access. Never paste keys into cells.

Default: first 3 IDs. Run all cells in order. Metadata/checkpoints live in SQLite;
source files remain alongside it. Old JSON is imported only when absent in SQL.
Use one running notebook per output directory. Do not run another arXiv downloader
in parallel. Database metadata is a cached snapshot, not an automatic refresh.
''')
    code('''%pip install -q "python-dotenv>=1.0" "pyarrow>=15"
''')
    code('''from pathlib import Path
import sys, zipfile, logging, os
ON_KAGGLE = Path('/kaggle/input').is_dir() and Path('/kaggle/working').is_dir()
if ON_KAGGLE:
    bundles = list(Path('/kaggle/input').rglob('arxiv_crawler_code.zip'))
    assert len(bundles) == 1, 'Attach exactly one code bundle dataset'
    CODE = Path('/kaggle/working/crawler_code')
    CODE.mkdir(exist_ok=True)
    with zipfile.ZipFile(bundles[0]) as z:
        for info in z.infolist():
            assert (CODE / info.filename).resolve().is_relative_to(CODE.resolve()), 'Unsafe ZIP path'
        z.extractall(CODE)
else:
    candidates = [Path.cwd(), *Path.cwd().parents]
    CODE = next((p for p in candidates if (p / 'src/crawl/pipeline.py').is_file()), None)
    assert CODE is not None, 'Open VS Code in the arxiv-reference-matching repo'
sys.path.insert(0, str(CODE))
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s', force=True)
if ON_KAGGLE:
    from kaggle_secrets import UserSecretsClient
    secrets = UserSecretsClient()
    os.environ['CONTACT_EMAIL'] = secrets.get_secret('CONTACT_EMAIL')
    os.environ['S2_API_KEY'] = secrets.get_secret('S2_API_KEY')
from src.common.config import get_settings, ArxivRange, load_env
if not ON_KAGGLE:
    load_env(CODE / '.env')
from src.crawl.pipeline import run, export_tables, snapshot
from src.crawl.store import Store
settings = get_settings()
settings.user_agent()
assert settings.s2_api_key, 'Set S2_API_KEY in .env or Kaggle Secrets'
ROOT = Path('/kaggle/working/arxiv_hai') if ON_KAGGLE else CODE / 'data/crawl_hai'
ROOT.mkdir(parents=True, exist_ok=True)
SNAPSHOT = ROOT.parent / 'arxiv_hai_snapshot.zip'
PREFIX, START, END, LIMIT = '2412', 8848, 13847, 3
IDS = list(ArxivRange(PREFIX, START, END).ids())[:LIMIT]
print('Selected IDs:', len(IDS), IDS[0], IDS[-1])
''')
    md('''## Optional: restore an earlier snapshot
Attach your saved snapshot ZIP as an input. Set RESTORE_ZIP to its exact path.
Restore only into a new workspace. A database alone is insufficient: source files
are required for checksum verification. Leave None for the first run.
''')
    code('''RESTORE_ZIP = None
if RESTORE_ZIP:
    assert not any(ROOT.iterdir()), 'Restore only into an empty directory'
    with zipfile.ZipFile(RESTORE_ZIP) as z:
        for info in z.infolist():
            assert (ROOT / info.filename).resolve().is_relative_to(ROOT.resolve())
        z.extractall(ROOT)
''')
    md('''## Crawl and checkpoint
Start with 3 IDs, then 50. Set LIMIT=5000 only after inspecting the sample.
SQLite saves each Version/page immediately. Kaggle snapshots after each batch;
local runs only snapshot at the end to avoid repeatedly compressing the corpus.
Snapshots in /kaggle/working still require saving/downloading to survive runtime loss.
Before ending a session, preserve `arxiv_hai_snapshot.zip` as private storage.
''')
    code('''summaries = []
try:
    for offset in range(0, len(IDS), 25):
        result = run(ROOT, IDS[offset:offset+25], settings.user_agent(), settings.s2_api_key)
        summaries.append(result)
        print(result)
        if ON_KAGGLE:
            snapshot(ROOT, SNAPSHOT)
finally:
    if (ROOT / 'crawl.sqlite').exists():
        snapshot(ROOT, SNAPSHOT)
''')
    code('''import sqlite3
with sqlite3.connect(ROOT / 'crawl.sqlite') as db:
    print('Versions:', db.execute('SELECT status,COUNT(*) FROM versions GROUP BY status').fetchall())
    print('Reference jobs:', db.execute('SELECT status,COUNT(*) FROM reference_jobs GROUP BY status').fetchall())
    print('All references:', db.execute('SELECT COUNT(*) FROM s2_references').fetchone()[0])
    print('With arXiv ID:', db.execute('SELECT COUNT(*) FROM s2_references WHERE ref_arxiv_id IS NOT NULL').fetchone()[0])
    print('S2 errors:', db.execute("SELECT arxiv_id,error FROM reference_jobs WHERE status='error' LIMIT 10").fetchall())
''')
    md('''## Export and save
Export uses the two existing M1 schemas. References from incomplete S2 jobs are
excluded, so inspect errors first: successful export does not mean M1 is complete.
ref_submission_date remains null until independently verified from arXiv.
All crawled references remain in SQLite; duplicate arXiv candidates export once.
''')
    code('''print(export_tables(ROOT, IDS))
print(snapshot(ROOT, SNAPSHOT))
''')
    md('''## Resume check
Rerun the crawl cell. Verified source and completed references should generate
zero network requests. Failed jobs resume from their last committed checkpoint.
M1 still needs coverage/error analysis, CPU benchmark and a Jupyter Book report.
Sources: https://info.arxiv.org/help/api/user-manual.html ;
https://api.semanticscholar.org/api-docs/graph ;
https://hcmus-cs-ta.github.io/lab-book/intro-ds/statement/crawling/
''')
    notebook = dict(cells=cells, metadata={'kernelspec': {'display_name': 'Python 3', 'language': 'python', 'name': 'python3'}}, nbformat=4, nbformat_minor=5)
    for index, cell in enumerate(cells):
        cell['id'] = f'cell-{index:02d}'
    path = root / 'notebooks' / 'crawl_kaggle.ipynb'
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(notebook, ensure_ascii=False, indent=2), encoding='utf-8')
    print(path)
    print(output / 'arxiv_crawler_code.zip')


if __name__ == '__main__':
    main()
