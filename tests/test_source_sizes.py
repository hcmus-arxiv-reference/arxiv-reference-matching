"""Size evaluation: bytes downloaded, content before selection, .tex/.bib kept."""
import gzip
import io
import json
import tarfile
import zipfile

from src.common.corpus import verified_source
from src.crawl.http_client import HttpClient, HttpResponse
from src.crawl.source import ArxivSourceDownloader, content_bytes
from scripts import measure_sizes

TEX = b'\\documentclass{article}\\begin{figure}\\includegraphics{fig.png}\\end{figure}'
PNG = b'\x89PNG' + b'\x00' * 5000


def tar_gz(files: dict[str, bytes]) -> bytes:
    data = io.BytesIO()
    with tarfile.open(fileobj=data, mode='w') as archive:
        for name, body in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(body)
            archive.addfile(info, io.BytesIO(body))
    return gzip.compress(data.getvalue())


def downloader(tmp_path, payload, name='raw'):
    client = HttpClient('offline', transport=lambda *_: HttpResponse(200, {}, payload),
                        sleeper=lambda _: None, max_retries=0)
    return ArxivSourceDownloader(client, tmp_path / name)


def test_content_bytes_undoes_compression_and_counts_every_file():
    payload = tar_gz({'main.tex': TEX, 'refs.bib': b'@a{b,}', 'fig.png': PNG})
    assert content_bytes(payload) == len(TEX) + 6 + len(PNG)
    assert content_bytes(gzip.compress(TEX)) == len(TEX)
    assert content_bytes(b'%PDF-1.7 body') == len(b'%PDF-1.7 body')
    docx = io.BytesIO()
    with zipfile.ZipFile(docx, 'w') as archive:
        archive.writestr('word/document.xml', 'x' * 300)
    assert content_bytes(docx.getvalue()) == 300


def test_receipt_records_three_sizes_and_stays_verified(tmp_path):
    payload = tar_gz({'main.tex': TEX, 'fig.png': PNG})
    result = downloader(tmp_path, payload).download('2508.02872', 1)
    receipt = json.loads((result.path / 'source.json').read_text())
    assert receipt['downloaded_bytes'] == len(payload)
    assert receipt['content_bytes'] == len(TEX) + len(PNG)
    assert list(receipt['files']) == ['main.tex']
    kept = (result.path / 'main.tex').read_bytes()
    assert kept == TEX  # figure commands kept byte for byte, only the image file is dropped
    assert verified_source(result.path) is not None


def test_measure_version_compares_kept_files_with_the_corpus(tmp_path):
    payload = tar_gz({'main.tex': TEX, 'fig.png': PNG})
    corpus = tmp_path / 'corpus'
    result = downloader(corpus, payload).download('2508.02872', 1)
    corpus = json.loads((result.path / 'source.json').read_text())['files']
    row = measure_sizes.measure_version(downloader(tmp_path, payload, 'work'), corpus, '2508.02872', 1)
    assert row['same_as_corpus'] is True and row['kept_bytes'] == len(TEX)
    assert row['content_bytes'] == len(TEX) + len(PNG)

    changed = tar_gz({'main.tex': TEX + b'%', 'fig.png': PNG})
    row = measure_sizes.measure_version(downloader(tmp_path, changed, 'work2'), corpus, '2508.02872', 1)
    assert row['same_as_corpus'] is False


def test_summary_compares_before_and_after_on_the_same_publications():
    rows = [
        {'arxiv_id': 'a', 'version': 1, 'downloaded_bytes': 40, 'content_bytes': 100,
         'kept_bytes': 10, 'same_as_corpus': True},
        {'arxiv_id': 'a', 'version': 2, 'downloaded_bytes': 60, 'content_bytes': 100,
         'kept_bytes': 30, 'same_as_corpus': True},
        {'arxiv_id': 'b', 'version': 1, 'downloaded_bytes': None, 'content_bytes': None,
         'kept_bytes': None, 'same_as_corpus': None},
    ]
    summary = measure_sizes.summarize(rows, ['a', 'b'], population=10)
    assert summary['measured_publications'] == 1 and summary['versions_not_measured'] == 1
    assert summary['avg_bytes_before_per_paper']['mean'] == 200
    assert summary['avg_bytes_after_per_paper']['mean'] == 40
    assert summary['size_reduction_pct'] == 80.0
    assert summary['download_to_content_ratio'] == 0.5


def test_plan_runs_without_the_corpus(tmp_path):
    payload = tar_gz({'main.tex': TEX, 'fig.png': PNG})
    files = json.loads((downloader(tmp_path, payload, 'corpus').download('2508.02872', 1).path
                        / 'source.json').read_text())['files']
    plan = {'format': 1, 'seed': 7, 'population_complete_publications': 1,
            'publications': [{'arxiv_id': '2508.02872', 'versions': 1, 'corpus_files': {'1': files}}]}
    plan = json.loads(json.dumps(plan))  # as read back from the plan file
    summary = measure_sizes.run_plan(plan, downloader(tmp_path, payload, 'work'), tmp_path / 'out')
    assert summary['measured_publications'] == 1 and summary['versions_differing_from_corpus'] == 0
    assert summary['seed'] == 7 and (tmp_path / 'out' / 'versions.csv').exists()
