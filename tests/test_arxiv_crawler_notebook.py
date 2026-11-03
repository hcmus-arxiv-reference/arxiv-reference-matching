"""Execute notebook source/extraction functions offline on synthetic archives."""
import ast
import gzip
import io
import json
from pathlib import Path
import tarfile
import time
from unittest.mock import Mock

import pytest
import requests


NOTEBOOK = Path(__file__).resolve().parents[1] / "src/arxiv_crawler.ipynb"


def cells():
    return ["".join(c.get("source", [])) for c in json.loads(NOTEBOOK.read_text(encoding="utf-8"))["cells"]]


def test_source_download_uses_contact_and_spaces_even_failed_requests(tmp_path):
    tree = ast.parse(cells()[2])
    functions = ast.Module(body=[n for n in tree.body if isinstance(n, ast.FunctionDef)], type_ignores=[])
    response = Mock(status_code=200)
    response.iter_content.return_value = [b"source"]
    context = Mock()
    context.__enter__ = Mock(return_value=response)
    context.__exit__ = Mock(return_value=False)
    http = Mock(get=Mock(return_value=context))
    clock = Mock()
    namespace = {"Path": Path, "SAVE_DIR": tmp_path, "SOURCE_USER_AGENT": "test contact",
                 "requests": http, "time": clock}
    exec(compile(functions, str(NOTEBOOK), "exec"), namespace)
    assert namespace["get_source"]("2412.08848v1") == 200
    assert (tmp_path / "2412.08848v1.tar.gz").read_bytes() == b"source"
    assert http.get.call_args.args[0] == "https://export.arxiv.org/src/2412.08848v1"
    assert http.get.call_args.kwargs["headers"] == {"User-Agent": "test contact"}
    clock.sleep.assert_called_with(3.1)
    http.get.side_effect = requests.ConnectionError("offline")
    with pytest.raises(requests.ConnectionError):
        namespace["get_source"]("2412.08848v2")
    assert clock.sleep.call_count == 2


def test_extraction_outputs_tex_bib_pdf_status_and_done(tmp_path):
    source = cells()
    ids = ["2412.08848v1", "2412.08848v2", "2412.08849v1"]
    ids_path = tmp_path / "ids.txt"
    ids_path.write_text("\n".join(ids), encoding="utf-8")
    with tarfile.open(tmp_path / f"{ids[0]}.tar.gz", "w:gz") as archive:
        for name, body in [("main.tex", b"\\documentclass{article}"),
                           ("refs.bib", b"@article{x,title={X}}"), ("figure.png", b"image")]:
            info = tarfile.TarInfo(name)
            info.size = len(body)
            archive.addfile(info, io.BytesIO(body))
    (tmp_path / f"{ids[1]}.tar.gz").write_bytes(gzip.compress(b"\\documentclass{article}\ntext"))
    (tmp_path / f"{ids[2]}.tar.gz").write_bytes(b"%PDF-1.7 synthetic")
    namespace = {"Path": Path, "SAVE_DIR": tmp_path, "IDS_TXT_DIR": ids_path,
                 "METADATA_OUTPUT_DIR": tmp_path / "metadata.json", "time": time}
    exec(compile(source[3], str(NOTEBOOK), "exec"), namespace)
    exec(compile(source[6], str(NOTEBOOK), "exec"), namespace)
    first = tmp_path / "2412-08848"
    assert (first / "v1/main.tex").exists()
    assert (first / "v1/refs.bib").exists()
    assert not (first / "v1/figure.png").exists()
    assert json.loads((first / "done.json").read_text())["n_versions"] == 2
    pdf = json.loads((tmp_path / "2412-08849/v1/status.json").read_text())
    assert (pdf["kind"], pdf["status"], pdf["files"]) == ("pdf", "empty", [])
    assert not list(tmp_path.rglob("*.parquet"))
    # A missing Version in the supplied ID list invalidates the done marker.
    ids_path.write_text("\n".join(ids + ["2412.08848v3"]), encoding="utf-8")
    namespace["write_done_files"]()
    assert not (first / "done.json").exists()
