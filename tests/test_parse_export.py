"""Kiểm thử gói M2.5 (Export, Invariants I1–I9, Pipeline tích hợp và Checkpoint/Resume)."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from scripts import m2_sample, parse_range
from src.common.corpus import file_digest
from src.common.schema import read_table, validate as validate_schema
from src.parse.bibtex import merge_bibtex
from src.parse.normalize import normalize
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

    # Normalizer thật phải giữ đúng output golden đã review.
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
    raw = r"\citestyle{numbers} See \cite{old1} and \citep[e.g.][p.~3]{old1, old2}."
    rewritten = rewrite_citations(raw, key_map)
    assert rewritten == r"\citestyle{numbers} See \cite{New2025} and \citep[e.g.][p.~3]{New2025, RefB}."

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
        normalize_fn=default_normalize,
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
    base = export_publication(
        arxiv_id,
        versions,
        bib_result,
        total_versions=total_versions,
        normalize_fn=default_normalize,
    )

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


def test_legacy_fallback_flag_still_uses_real_modules(tmp_path: Path) -> None:
    corpus_dir = tmp_path / "corpus"
    m2_sample.make_mock(corpus_dir, size=2, seed=20261112)
    metrics = run_batch(corpus_dir, tmp_path / "out", allow_fallback=True)
    assert metrics["publications_succeeded"] == 2
    assert metrics["allow_fallback"] is False
    assert metrics["fallback_modules"] == []
    assert get_module_versions(allow_fallback=True) == get_module_versions()
    assert not any(value.startswith("fallback-") for value in metrics["module_versions"].values())


def test_real_pipeline_merges_bibliography_before_normalizing_citations(tmp_path: Path) -> None:
    corpus_dir = tmp_path / "corpus"
    aid = "2508.02872"
    key = "2508-02872"
    case_dir = FIXTURES_DIR / "two-versions-cite-rename"
    # Raw .tex/.bib fixtures are ignored by Git; materialize tracked JSON inputs.
    for version in (1, 2):
        directory = corpus_dir / "raw" / key / f"v{version}"
        directory.mkdir(parents=True)
        bundle = json.loads((case_dir / f"A.v{version}.json").read_text(encoding="utf-8"))
        bib_source = json.loads((case_dir / f"B'.v{version}.json").read_text(encoding="utf-8"))
        contents = {"main.tex": bundle["text"], **bib_source["bib_files"]}
        for name, content in contents.items():
            (directory / name).write_text(content, encoding="utf-8")
        files = {name: file_digest(directory / name) for name in contents}
        (directory / "source.json").write_text(json.dumps({
            "format": 1, "arxiv_id": aid, "version": version,
            "status": "success", "checksum": files["main.tex"], "files": files,
        }), encoding="utf-8")
    metadata_dir = corpus_dir / "metadata"
    metadata_dir.mkdir()
    (metadata_dir / f"{key}.json").write_text(json.dumps({
        "format": 1,
        "publication": {
            "arxiv_id": aid, "title": "Synthetic citation rename fixture",
            "authors": ["Example Author"], "submission_date": "2025-08-04",
            "revised_dates": ["2025-08-05"],
            "venue": None, "versions": 2,
        },
    }), encoding="utf-8")
    normalized_inputs = []

    def record_normalize(kind: str, raw: str) -> str:
        normalized_inputs.append(raw)
        return normalize(kind, raw)

    result = parse_publication(corpus_dir, aid, normalize_fn=record_normalize).result
    assert [row["status"] for row in result.version_logs] == ["parsed", "parsed"]
    assert [row["citation_key"] for row in result.bibtex] == ["Smith2020"]
    assert any(r"\cite{Smith2020}" in raw for raw in normalized_inputs)
    assert all(r"\cite{smith20}" not in raw for raw in normalized_inputs)
    shared = [row for row in result.elements if r"\cite{Smith2020}" in row["content"]]
    assert len(shared) == 1
    assert {edge["version"] for edge in result.hierarchy
            if edge["element_id"] == shared[0]["element_id"]} == {1, 2}
    assert validate_E(result, expected_versions=2, raise_on_error=False) == []


def test_pipeline_batch_determinism_and_checkpoint_resume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    corpus_dir = tmp_path / "corpus"
    m2_sample.make_mock(corpus_dir, size=5, seed=20261112)

    out_one = tmp_path / "out_one"
    out_two = tmp_path / "out_two"
    metrics_one = run_batch(
        corpus_dir, out_one, metrics_path=tmp_path / "m1.json"
    )
    metrics_two = run_batch(
        corpus_dir, out_two, metrics_path=tmp_path / "m2.json"
    )

    assert metrics_one["publications_total"] == 5
    assert metrics_one["publications_succeeded"] == 5
    assert metrics_one["publications_resumed"] == 0
    assert metrics_one["allow_fallback"] is False
    assert metrics_one["fallback_modules"] == []
    assert metrics_one["versions_total_metadata"] == (
        metrics_one["versions_parsed"]
        + metrics_one["versions_empty_non_tex"]
        + metrics_one["versions_empty_unavailable"]
    )
    assert metrics_one["tables_dir_size_mb"] <= metrics_one["output_dir_size_mb"]

    # Log không còn dùng gói thay thế.
    log_lines = [
        json.loads(line)
        for line in (out_one / "log" / "versions.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    parsed_logs = [row for row in log_lines if row["status"] == "parsed"]
    assert parsed_logs and all(not row.get("fallbacks") for row in parsed_logs)

    # I7: Chạy hai lần ra file giống hệt từng byte (log/versions.jsonl và 3 bảng Parquet)
    assert (out_one / "log" / "versions.jsonl").read_bytes() == (
        out_two / "log" / "versions.jsonl"
    ).read_bytes()
    for name in ("elements", "hierarchy", "bibtex"):
        p1 = out_one / "tables" / f"{name}.parquet"
        p2 = out_two / "tables" / f"{name}.parquet"
        assert p1.read_bytes() == p2.read_bytes()

    outputs = [Path("log/versions.jsonl"), *(
        Path("tables") / f"{name}.parquet" for name in ("elements", "hierarchy", "bibtex")
    )]
    before_resume = {path: (out_one / path).read_bytes() for path in outputs}

    # Resume không làm lại Publication đã xong khi dùng cùng cấu hình module
    failing_assembler = Mock(side_effect=AssertionError("Should not be called on resume"))
    monkeypatch.setattr("src.parse.pipeline.assemble_source", failing_assembler)
    resumed_metrics = run_batch(corpus_dir, out_one)
    assert resumed_metrics["publications_resumed"] == 5
    failing_assembler.assert_not_called()
    assert all((out_one / path).read_bytes() == content
               for path, content in before_resume.items())

    # CLI mặc định chạy đầu-cuối bằng các gói thật.
    monkeypatch.undo()
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
    assert EXPORT_VERSION == "3" and PIPELINE_VERSION == "6"
    versions = get_module_versions(allow_fallback=True)
    assert "export" in versions


def _tex_publication_ids(corpus_dir: Path) -> list[str]:
    """Lọc các Publication trong corpus có ít nhất một Version TeX (status == 'success')."""
    from src.common.corpus import FileCorpus, verified_source

    corpus = FileCorpus(corpus_dir)
    ids: list[str] = []
    for meta_path in sorted((corpus_dir / "metadata").glob("*.json")):
        aid = json.loads(meta_path.read_text(encoding="utf-8"))["publication"]["arxiv_id"]
        pub = corpus.read_publication(aid)
        if any(
            (v := verified_source(corpus.version_path(aid, ver))) is not None
            and v.status == "success"
            for ver in range(1, pub.versions + 1)
        ):
            ids.append(aid)
    return ids


def test_run_batch_isolates_publication_error_and_skips_done_checkpoint(tmp_path: Path) -> None:
    corpus_dir = tmp_path / "corpus"
    m2_sample.make_mock(corpus_dir, size=5, seed=20261112)
    tex_ids = _tex_publication_ids(corpus_dir)
    assert len(tex_ids) >= 2
    bad_id = tex_ids[0]

    def failing_bibtex(arxiv_id: str, sources: list) -> BibResult:
        if arxiv_id == bad_id:
            raise ValueError("Simulated I5/BibTeX failure")
        return merge_bibtex(arxiv_id, sources)

    out_dir = tmp_path / "out"
    metrics = run_batch(
        corpus_dir,
        out_dir,
        bibtex_fn=failing_bibtex,
    )
    assert metrics["publications_total"] == 5
    assert metrics["publications_succeeded"] == 4
    assert metrics["publications_failed"] == 1
    assert (out_dir / "tables" / "elements.parquet").is_file()
    assert not (out_dir / bad_id.replace(".", "-") / "done.json").exists()

    logs = [
        json.loads(line)
        for line in (out_dir / "log" / "versions.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    bad_logs = [row for row in logs if row["arxiv_id"] == bad_id]
    assert bad_logs and all(
        row["status"] == "failed" and "publication_error:ValueError" in row["issues"]
        for row in bad_logs
    )


def test_pipeline_handles_needs_review_and_unavailable_c11(tmp_path: Path) -> None:
    from src.parse.source import Issue, SourceBundle, assemble_source

    corpus_dir = tmp_path / "corpus"
    m2_sample.make_mock(corpus_dir, size=5, seed=20261112)
    tex_ids = _tex_publication_ids(corpus_dir)
    assert len(tex_ids) >= 2
    id_review, id_unavail = tex_ids[0], tex_ids[1]

    # Biến v1 của id_unavail thành receipt status="unavailable" (C11)
    unavail_v1 = corpus_dir / "raw" / id_unavail.replace(".", "-") / "v1"
    for f in list(unavail_v1.iterdir()):
        if f.name != "source.json":
            f.unlink()
    (unavail_v1 / "source.json").write_text(
        json.dumps(
            {
                "format": 1,
                "arxiv_id": id_unavail,
                "version": 1,
                "status": "unavailable",
                "http_status": 404,
                "checksum": "",
                "files": {},
            }
        ),
        encoding="utf-8",
    )

    def review_assembler(vdir: Path) -> SourceBundle:
        sb = assemble_source(vdir)
        if id_review.replace(".", "-") in str(vdir) and sb.status == "ready":
            return SourceBundle(
                status="needs_review",
                root=sb.root,
                text=sb.text,
                files=sb.files,
                unused_tex_files=sb.unused_tex_files,
                checksums=sb.checksums,
                spans=sb.spans,
                includes=sb.includes,
                issues=[
                    *sb.issues,
                    Issue(
                        code="unsupported_conditional",
                        severity="warning",
                        file=sb.root or "main.tex",
                        line=1,
                        message="test warning",
                    ),
                ],
                assembler_version=sb.assembler_version,
            )
        return sb

    out_dir = tmp_path / "out"
    metrics = run_batch(
        corpus_dir,
        out_dir,
        arxiv_ids=[id_review, id_unavail],
        assemble_fn=review_assembler,
    )
    logs = [
        json.loads(line)
        for line in (out_dir / "log" / "versions.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    review_logs = [r for r in logs if r["arxiv_id"] == id_review]
    assert any(
        r["status"] == "parsed" and "unsupported_conditional" in r["issues"] for r in review_logs
    )
    unavail_v1_logs = [r for r in logs if r["arxiv_id"] == id_unavail and r["version"] == 1]
    assert len(unavail_v1_logs) == 1
    assert unavail_v1_logs[0]["status"] == "empty_unavailable"
    assert metrics["versions_empty_unavailable"] >= 1
    assert metrics["publications_failed"] == 0


def test_structure_type_error_is_not_masked_by_fallback_call(tmp_path: Path) -> None:
    corpus_dir = tmp_path / "corpus"
    m2_sample.make_mock(corpus_dir, size=5, seed=20261112)
    aid = _tex_publication_ids(corpus_dir)[0]

    calls = 0

    def buggy_structure(sb, arxiv_id: str, ver: int, vdir: Path):
        nonlocal calls
        calls += 1
        raise TypeError("internal bug in build_structure")

    outcome = parse_publication(
        corpus_dir,
        aid,
        structure_fn=buggy_structure,
    )
    assert calls >= 1
    assert any(
        log["status"] == "failed" and "parse_error:TypeError" in log["issues"]
        for log in outcome.result.version_logs
    )


def test_checkpoint_key_reflects_custom_stage_function(tmp_path: Path) -> None:
    corpus_dir = tmp_path / "corpus"
    m2_sample.make_mock(corpus_dir, size=5, seed=20261112)
    aid = _tex_publication_ids(corpus_dir)[0]
    out_dir = tmp_path / "out"

    m1 = run_batch(corpus_dir, out_dir, arxiv_ids=[aid])
    assert m1["publications_resumed"] == 0

    def custom_normalize(kind: str, raw: str) -> str:
        base = default_normalize(kind, raw)
        return f"[CUSTOM] {base}" if kind == "sentence" else base

    m2 = run_batch(
        corpus_dir, out_dir, arxiv_ids=[aid], normalize_fn=custom_normalize
    )
    assert m2["publications_resumed"] == 0
    assert m2["module_versions"]["normalize"].startswith("custom:")
    tbl = read_table("elements", out_dir / "tables" / "elements.parquet")
    sentences = [
        row["content"] for row in tbl.to_pylist() if row["kind"] == "sentence"
    ]
    assert sentences and all(s.startswith("[CUSTOM] ") for s in sentences)


def test_export_uses_real_normalizer_and_rejects_excess_version() -> None:
    tree = _cite_tree("Hello.")
    result = export_publication(
        "2508.02872",
        [VersionInput(version=1, status="parsed", leaf_tree=tree)],
        BibResult(arxiv_id="2508.02872", entries=[], key_map={"1": {}}),
    )
    assert validate_E(result, expected_versions=1, raise_on_error=False) == []
    assert default_normalize is normalize
    with pytest.raises(ValueError, match="total_versions"):
        export_publication(
            "2508.02872",
            [VersionInput(version=1, status="parsed", leaf_tree=tree),
             VersionInput(version=2, status="missing")],
            total_versions=1,
        )


def _cite_tree(raw: str) -> LeafTree:
    return LeafTree(
        arxiv_id="2508.02872",
        version=1,
        root=Section(
            kind="document",
            title_raw="",
            starred=False,
            span=(0, len(raw)),
            children=[Leaf(kind="sentence", raw=raw, span=(0, len(raw)))],
        ),
    )


def test_i5_accepts_logged_missing_entry_but_rejects_other_unknown_keys() -> None:
    """Key thiếu entry đã ghi missing_entry (data-contract 4.2) không làm hỏng cả Publication."""
    entry = {"citation_key": "known", "entry_type": "article", "title": "Known", "authors": [],
             "year": 2020, "doi": None, "journal": None, "url": None}
    logged = BibResult(
        arxiv_id="2508.02872",
        entries=[entry],
        key_map={"1": {"known": "known"}},
        stats={"unresolved": 1, "unresolved_keys": [
            {"version": 1, "key": "ghost", "reason": "missing_entry"},
        ]},
    )
    res = export_publication(
        "2508.02872",
        [VersionInput(version=1, status="parsed", leaf_tree=_cite_tree(r"See \cite{known,ghost}."))],
        logged,
        normalize_fn=default_normalize,
    )
    assert res.unresolved_keys == frozenset({"ghost"})
    assert res.stats["bibtex_unresolved_keys"] == 1
    assert [row["citation_key"] for row in res.bibtex] == ["known"]

    unlogged = BibResult(arxiv_id="2508.02872", entries=[entry], key_map={"1": {"known": "known"}})
    with pytest.raises(ValueError, match=r"\[I5\].*ghost"):
        export_publication(
            "2508.02872",
            [VersionInput(version=1, status="parsed", leaf_tree=_cite_tree(r"See \cite{known,ghost}."))],
            unlogged,
            normalize_fn=default_normalize,
        )



def test_checkpoint_roundtrip_keeps_unresolved_keys(tmp_path: Path) -> None:
    """export.json lưu unresolved_keys, nên resume vẫn qua I5 thay vì tính lại cả Publication."""
    from src.parse.pipeline import _load_publication_checkpoint, _save_publication_checkpoint

    logged = BibResult(
        arxiv_id="2508.02872",
        entries=[],
        key_map={"1": {}},
        stats={"unresolved": 1, "unresolved_keys": [
            {"version": 1, "key": "ghost", "reason": "missing_entry"},
        ]},
    )
    res = export_publication(
        "2508.02872",
        [VersionInput(version=1, status="parsed", leaf_tree=_cite_tree(r"See \cite{ghost}."))],
        logged,
        normalize_fn=default_normalize,
    )
    versions = {"export": EXPORT_VERSION}
    _save_publication_checkpoint(tmp_path, res, "sha", versions)
    loaded = _load_publication_checkpoint(tmp_path, "2508.02872", "sha", versions, expected_versions=1)
    assert loaded is not None
    assert loaded.unresolved_keys == frozenset({"ghost"})
    assert loaded.elements == res.elements
