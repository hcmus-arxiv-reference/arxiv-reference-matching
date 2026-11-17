"""Every verified TeX Version counts, including assembly failures."""
import json
import sys

from scripts.measure_source_range import main
from src.common.corpus import file_digest


def test_range_denominator(tmp_path, monkeypatch):
    for n, text in enumerate([r"\documentclass{article}ok", "missing root", None], 1):
        directory = tmp_path / "2508-02872" / f"v{n}"
        directory.mkdir(parents=True)
        files = {}
        if text:
            tex = directory / "main.tex"
            tex.write_text(text)
            files[tex.name] = file_digest(tex)
        receipt = dict(format=1, arxiv_id="2508.02872", version=n, files=files,
                       checksum="fixture", status="success" if text else "non_tex")
        (directory / "source.json").write_text(json.dumps(receipt))
    report = tmp_path / "report.json"
    monkeypatch.setattr(sys, "argv", ["measure", str(tmp_path), "--revision", "fixture",
                        "--output", str(report), "--details", str(tmp_path / "rows.json"),
                        "--workers", "1"])
    main()
    result = json.loads(report.read_text())
    assert result["versions"] == 3
    assert result["ready_tex_versions"] == 1
    assert result["tex_versions"] == 2
    assert result["ready_fraction"] == 0.5
