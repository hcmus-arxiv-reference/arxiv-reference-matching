"""String output must retain the compilation order without changing sources."""

from pathlib import Path
import subprocess
import sys

import pytest

from src.crawl.http_client import HttpResponse
from src.crawl.source import ArxivSourceDownloader
from src.parse.MultifileGathering.merge import merge_latex


def source(folder, files):
    for name, text in files.items():
        path = folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


def test_nested_and_repeated_inputs_preserve_order_without_writing_files(tmp_path):
    source(tmp_path, {
        "main.tex": r"\documentclass{article}A\input{parts/one}B\input{parts/one}C",
        "parts/one.tex": r"ONE\include{two}",
        "parts/two.tex": "TWO", "unused.tex": "UNUSED",
    })
    before = {p.relative_to(tmp_path): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    assert merge_latex(tmp_path) == r"\documentclass{article}AONETWOBONETWOC"
    assert {p.relative_to(tmp_path): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()} == before


def test_includeonly_from_preamble_does_not_filter_input(tmp_path):
    source(tmp_path, {
        "main.tex": (r"\documentclass{article}\input{settings}\begin{document}"
                     r"\include{intro}\include{method}\input{note}\end{document}"),
        "settings.tex": r"\includeonly{intro}",
        "intro.tex": "INTRO", "method.tex": "EXCLUDED", "note.tex": "NOTE",
    })
    assert merge_latex(tmp_path) == (
        r"\documentclass{article}\includeonly{intro}\begin{document}INTRONOTE\end{document}"
    )


def test_commented_input_is_preserved_as_text_and_not_expanded(tmp_path):
    source(tmp_path, {"main.tex": "\\documentclass{article}\n% \\input{missing}\nBody."})
    assert merge_latex(tmp_path) == (tmp_path / "main.tex").read_text()


def test_explicit_main_disambiguates_multiple_roots(tmp_path):
    source(tmp_path, {
        "main.tex": r"\documentclass{article}MAIN",
        "supplementary.tex": r"\documentclass{article}SUPPLEMENT",
    })
    with pytest.raises(ValueError, match="ambiguous_root"):
        merge_latex(tmp_path)
    assert merge_latex(tmp_path, "main.tex") == r"\documentclass{article}MAIN"


@pytest.mark.parametrize("body,diagnostic", [
    (r"\input{missing}", "include_error"),
    (r"\input{main}", "include_error"),
    (r"\input{../outside}", "include_error"),
    (r"\newcommand{\path}{sections}\input{\path/intro}", "include_error"),
    (r"\newcommand{\load}{\input{part}}\load", "macro_compilation_path"),
])
def test_partial_or_unsupported_sources_raise_instead_of_returning_text(tmp_path, body, diagnostic):
    source(tmp_path, {"main.tex": r"\documentclass{article}" + body})
    with pytest.raises(ValueError, match=diagnostic):
        merge_latex(tmp_path)


def test_verified_non_tex_version_returns_empty_string(tmp_path):
    class Client:
        def get(self, url, **options):
            return HttpResponse(200, {}, b"%PDF-1.7 synthetic")

    result = ArxivSourceDownloader(Client(), tmp_path / "raw").download("2508.02872", 1)
    assert merge_latex(result.path) == ""


def test_direct_cli_prints_only_merged_string_from_another_directory(tmp_path):
    folder = tmp_path / "source"
    source(folder, {"main.tex": r"\documentclass{article}\input{part}", "part.tex": "Nội dung."})
    script = Path(__file__).resolve().parents[1] / "src/parse/MultifileGathering/merge.py"
    result = subprocess.run(
        [sys.executable, str(script), str(folder), "--main-file", "main.tex"],
        cwd=tmp_path, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == r"\documentclass{article}Nội dung."
    assert result.stderr == ""


def test_direct_cli_failure_does_not_print_partial_latex(tmp_path):
    source(tmp_path, {"main.tex": r"\documentclass{article}BEFORE\input{missing}"})
    script = Path(__file__).resolve().parents[1] / "src/parse/MultifileGathering/merge.py"
    result = subprocess.run(
        [sys.executable, str(script), str(tmp_path)], capture_output=True, text=True,
    )
    assert result.returncode == 2
    assert result.stdout == ""
    assert "include_error" in result.stderr
