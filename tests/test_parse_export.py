"""Kiểm thử gói M2.5 (Export, Invariants I1–I9, Pipeline tích hợp và Checkpoint/Resume)."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from scripts import m2_sample, parse_range
from src.common.schema import read_table, validate as validate_schema
from src.parse.export import (
    EXPORT_VERSION,
    ExportResult,
    VersionInput,
    default_normalize,
    export_publication,
    format_csv_bundle,
    load_golden_case,
    merge_export_tables,
    rewrite_citations,
    validate_E,
    write_export_tables,
)
from src.parse.pipeline import (
    PIPELINE_VERSION,
    get_module_versions,
    parse_publication,
    run_batch,
)
from src.parse.types import (
    BibResult,
    Leaf,
    LeafTree,
    ListNode,
    Section,
)

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "m2"


@pytest.mark.parametrize("case_name", ["two-versions-cite-rename", "non-tex-version"])
def test_golden_cases_match_expected_outputs_and_invariants(case_name: str, tmp_path: Path) -> None:
    case_dir = FIXTURES_DIR / case_name
    arxiv_id, total_versions, versions, bib_result = load_golden_case(case_dir)

    # Dùng normalize giữ nguyên khoảng trắng bên trong toán để khớp fixture mẫu tay,
    # đồng thời kiểm tra đổi \cite diễn ra trước normalize.
    result = export_publication(
        arxiv_id,
        versions,
        bib_result,
        total_versions=total_versions,
        normalize_fn=default_normalize,
    )
    assert validate_E(result, expected_versions=total_versions, raise_on_error=False) == []

    bundle = format_csv_bundle(result)
    expected_dir = case_dir / "E"
    for filename, content in bundle.items():
        expected_text = (expected_dir / filename).read_text(encoding="utf-8")
        assert content == expected_text, f"Lệch {filename} trong golden case {case_name}"

    tables = merge_export_tables([result])
    written = write_export_tables(tables, tmp_path / "tables")
    for name, path in written.items():
        tbl = read_table(name, path)
        assert validate_schema(tbl, name) == []


def test_cite_rewrite_and_default_normalize_are_idempotent() -> None:
    key_map = {"old1": "New2025", "old2": "RefB"}
    raw = r"See \cite{old1} and \citep[e.g.][p.~3]{old1, old2}."
    rewritten = rewrite_citations(raw, key_map)
    assert rewritten == r"See \cite{New2025} and \citep[e.g.][p.~3]{New2025, RefB}."

    samples = [
        ("sentence", r"\noindent We use \(x + y = 1\) and \begin{math}z=2\end{math}   here."),
        ("formula", r"\[ E = mc^2 \]"),
        ("formula", "\\begin{align*}\n a &= b \\\\\n c &= d\n\\end{align*}"),
        ("figure", "\\begin{figure}[htpb]\n\\centering\n\\toprule\n\\caption{ Demo }\n\\end{figure}"),
        ("section", r"\small   Introduction   "),
    ]
    for kind, text in samples:
        once = default_normalize(kind, text)
        twice = default_normalize(kind, once)
        assert once == twice
    assert default_normalize("formula", r"$$a+b$$") == r"\begin{equation}a+b\end{equation}"
    assert r"\centering" not in default_normalize("figure", samples[3][1])
    assert "[htpb]" not in default_normalize("figure", samples[3][1])


def test_duplicate_siblings_merge_edges_and_shared_element_under_two_parents() -> None:
    arxiv_id = "2508.02872"
    dup_leaf_1 = Leaf(kind="sentence", raw="Repeated sentence.", span=(10, 28))
    dup_leaf_2 = Leaf(kind="sentence", raw="Repeated sentence.", span=(29, 47))
    shared_leaf = Leaf(kind="sentence", raw="Shared across sections.", span=(50, 73))

    sec_a = Section(
        kind="section",
        title_raw="Sec A",
        starred=False,
        span=(0, 80),
        children=[dup_leaf_1, dup_leaf_2, shared_leaf],
    )
    sec_b = Section(
        kind="section",
        title_raw="Sec B",
        starred=False,
        span=(81, 120),
        children=[Leaf(kind="sentence", raw="Shared across sections.", span=(90, 113))],
    )
    root = Section(
        kind="document",
        title_raw="",
        starred=False,
        span=(0, 120),
        children=[sec_a, sec_b],
    )
    lt = LeafTree(arxiv_id=arxiv_id, version=1, root=root)
    res = export_publication(
        arxiv_id,
        [VersionInput(version=1, status="parsed", leaf_tree=lt)],
        BibResult(arxiv_id=arxiv_id, entries=[], key_map={"1": {}}),
    )
    assert res.version_logs[0]["duplicate_sibling_edges"] == 1
    assert len(res.order["1"][sec_a_id := res.hierarchy[0]["parent_id"]]) == 3
    # Câu dùng chung dưới Sec A và Sec B tạo 2 cạnh khác parent_id
    shared_id = [e["element_id"] for e in res.elements if e["content"] == "Shared across sections."][0]
    shared_parents = [h["parent_id"] for h in res.hierarchy if h["element_id"] == shared_id]
    assert len(shared_parents) == 2 and len(set(shared_parents)) == 2
    assert sec_a_id in shared_parents


def test_validate_e_detects_all_invariant_violations() -> None:
    case_dir = FIXTURES_DIR / "two-versions-cite-rename"
    arxiv_id, total_versions, versions, bib_result = load_golden_case(case_dir)
    base = export_publication(arxiv_id, versions, bib_result, total_versions=total_versions)

    # I1: parent_id không tồn tại trong elements
    bad_i1 = deepcopy(base)
    bad_i1.hierarchy[0]["parent_id"] = "2508-02872#section-0000000000000000"
    errs = validate_E(bad_i1, raise_on_error=False)
    assert any("[I1]" in e for e in errs)

    # I2: không có root document (xóa document khỏi elements)
    bad_i2 = deepcopy(base)
    bad_i2.elements = [e for e in bad_i2.elements if e["kind"] != "document"]
    errs = validate_E(bad_i2, raise_on_error=False)
    assert any("[I2]" in e or "[I1]" in e for e in errs)

    # I3: Section có tiêu đề References
    bad_i3 = deepcopy(base)
    for e in bad_i3.elements:
        if e["kind"] == "section":
            e["content"] = "References"
            break
    errs = validate_E(bad_i3, raise_on_error=False)
    assert any("[I3]" in e for e in errs)

    # I4: sentence làm cha
    bad_i4 = deepcopy(base)
    sent_ids = [e["element_id"] for e in bad_i4.elements if e["kind"] == "sentence"]
    bad_i4.hierarchy[0]["parent_id"] = sent_ids[1]
    errs = validate_E(bad_i4, raise_on_error=False)
    assert any("[I4]" in e for e in errs)

    # I5: trích dẫn key không có trong bibtex
    bad_i5 = deepcopy(base)
    bad_i5.bibtex = []
    errs = validate_E(bad_i5, raise_on_error=False)
    assert any("[I5]" in e for e in errs)

    # I6: hai Version có cùng root nhưng tập cạnh khác nhau
    bad_i6 = deepcopy(base)
    bad_i6.root_by_version[2] = bad_i6.root_by_version[1]
    errs = validate_E(bad_i6, raise_on_error=False)
    assert any("[I6]" in e for e in errs)

    # I8: số dòng log không khớp số Version theo metadata
    errs = validate_E(base, expected_versions=3, raise_on_error=False)
    assert any("[I8]" in e for e in errs)


def test_pipeline_batch_determinism_and_checkpoint_resume(tmp_path: Path) -> None:
    corpus_dir = tmp_path / "corpus"
    m2_sample.make_mock(corpus_dir, size=5, seed=20261112)

    out_one = tmp_path / "out_one"
    out_two = tmp_path / "out_two"
    metrics_one = run_batch(corpus_dir, out_one, metrics_path=tmp_path / "m1.json")
    metrics_two = run_batch(corpus_dir, out_two, metrics_path=tmp_path / "m2.json")

    assert metrics_one["publications_total"] == 5
    assert metrics_one["publications_succeeded"] == 5
    assert metrics_one["publications_resumed"] == 0
    assert metrics_one["versions_total_metadata"] == (
        metrics_one["versions_parsed"] + metrics_one["versions_empty_non_tex"]
    )

    # I7: Chạy hai lần ra file giống hệt từng byte (log/versions.jsonl và 3 bảng Parquet)
    assert (out_one / "log" / "versions.jsonl").read_bytes() == (
        out_two / "log" / "versions.jsonl"
    ).read_bytes()
    for name in ("elements", "hierarchy", "bibtex"):
        p1 = out_one / "tables" / f"{name}.parquet"
        p2 = out_two / "tables" / f"{name}.parquet"
        assert p1.read_bytes() == p2.read_bytes()

    # Resume không làm lại Publication đã xong
    failing_assembler = Mock(side_effect=AssertionError("Should not be called on resume"))
    resumed_metrics = run_batch(
        corpus_dir, out_one, assemble_fn=failing_assembler
    )
    assert resumed_metrics["publications_resumed"] == 5
    failing_assembler.assert_not_called()

    # CLI scripts.parse_range hoạt động đầu-cuối
    cli_out = tmp_path / "cli_out"
    cli_metrics = tmp_path / "cli_metrics.json"
    rc = parse_range.main(
        [
            "--data-dir",
            str(corpus_dir),
            "--out-dir",
            str(cli_out),
            "--metrics",
            str(cli_metrics),
        ]
    )
    assert rc == 0
    assert cli_metrics.is_file()
    assert EXPORT_VERSION == "1" and PIPELINE_VERSION == "1"
    assert "export" in get_module_versions()
