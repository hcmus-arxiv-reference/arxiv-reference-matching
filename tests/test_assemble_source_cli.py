"""CLI integration with synthetic, checksum-verified crawler receipts."""
import json

import pytest

from scripts.assemble_source import main
from src.crawl.http_client import HttpResponse
from src.crawl.source import ArxivSourceDownloader


def source(tmp_path, payload):
    class Client:
        def get(self, url):
            return HttpResponse(200, {}, payload)
    return ArxivSourceDownloader(Client(), tmp_path / "raw").download("2508.02872", 1).path


def test_cli_writes_reproducible_artifact_and_preserves_raw(tmp_path):
    path = source(tmp_path, b"\\documentclass{article}\n\\begin{document}Body.\\end{document}")
    before = {p.name: p.read_bytes() for p in path.iterdir()}
    output = tmp_path / "assembled.json"
    args = ["--source-dir", str(path), "--output", str(output)]
    assert main(args) == 0
    first = output.read_bytes()
    assert main(args) == 0 and output.read_bytes() == first
    assert {p.name: p.read_bytes() for p in path.iterdir()} == before
    payload = json.loads(first)
    assert payload["status"] == "ready" and payload["root"] == "single.tex"
    assert payload["spans"][0]["file"] == "single.tex"


def test_cli_refuses_output_inside_source(tmp_path):
    path = source(tmp_path, b"\\documentclass{article}")
    with pytest.raises(SystemExit) as error:
        main(["--source-dir", str(path), "--output", str(path / "source.json")])
    assert error.value.code == 2


@pytest.mark.parametrize("payload,status", [(b"%PDF-1.7 fake", "empty_non_tex"),
                                           (b"\\documentclass{article}\\input{missing}", "error")])
def test_cli_distinguishes_empty_from_failure(tmp_path, payload, status):
    path = source(tmp_path, payload)
    output = tmp_path / "assembled.json"
    assert main(["--source-dir", str(path), "--output", str(output)]) == (0 if status == "empty_non_tex" else 2)
    assert json.loads(output.read_text())["status"] == status


def test_cli_rejects_corrupt_input(tmp_path):
    path = source(tmp_path, b"\\documentclass{article}")
    (path / "single.tex").write_text(r"\documentclass{article}modified")
    output = tmp_path / "assembled.json"
    assert main(["--source-dir", str(path), "--output", str(output)]) == 2
    assert json.loads(output.read_text())["issues"][0]["code"] == "invalid_receipt"
