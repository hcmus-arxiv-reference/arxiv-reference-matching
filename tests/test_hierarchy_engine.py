"""Native integration tests; build with python -m src.parse.Hierarchy.build first."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
import hashlib
import json

import pytest

pytest.importorskip(
    "src.parse.Hierarchy._hierarchy_native",
    reason="Build the native module with python -m src.parse.Hierarchy.build",
)

from src.common.schema import from_records, validate
from src.parse.Hierarchy import HierarchyEngine, ParseResult
from src.parse.Hierarchy.engine import DEFAULT_MAPPING
from src.parse.Hierarchy.types import Element, Hierarchy
from src.parse.MultifileGathering.merge import merge_latex


def test_native_result_uses_existing_dataclasses_and_table_schemas():
    result = HierarchyEngine("2508.02872", 2).parse(r"\section{Intro}First. Second.")
    assert isinstance(result, ParseResult)
    assert result.complete
    assert all(isinstance(element, Element) for element in result.elements)
    assert all(isinstance(edge, Hierarchy) and edge.version == 2 for edge in result.hierarchy)
    for name, rows in (("elements", result.elements), ("hierarchy", result.hierarchy)):
        table = from_records([asdict(row) for row in rows], name)
        assert validate(table, name) == []
    ids = {element.element_id for element in result.elements}
    assert all(edge.element_id in ids and edge.parent_id in ids for edge in result.hierarchy)


def test_unicode_content_and_hash_match_python_sha256():
    content = "Nội dung tiếng Việt."
    result = HierarchyEngine("2508.02872", 1).parse("\\section{Giới thiệu}" + content)
    sentence = next(element for element in result.elements if element.kind == "sentence")
    assert sentence.content == content
    digest = hashlib.sha256(json.dumps(["sentence", content], ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()[:16]
    assert sentence.element_id == f"2508-02872#sentence-{digest}"
    assert result.complete


def test_duplicate_edges_and_intermediate_order_survive_bridge():
    result = HierarchyEngine("2508.02872", 1).parse(r"\section{Intro}Same. Same.")
    sentence = next(element for element in result.elements if element.kind == "sentence")
    section = next(element for element in result.elements if element.kind == "section")
    assert result.ordered_children[section.element_id] == [sentence.element_id, sentence.element_id]
    assert sum(edge.element_id == sentence.element_id for edge in result.hierarchy) == 1


def test_engine_can_be_reused_without_leaking_state():
    engine = HierarchyEngine("2508.02872", 1)
    first = engine.parse("First.")
    second = engine.parse("Second.")
    assert [element.content for element in first.elements if element.kind == "sentence"] == ["First."]
    assert [element.content for element in second.elements if element.kind == "sentence"] == ["Second."]
    assert engine.parse("First.") == first


def test_diagnostics_preserve_utf8_byte_offsets_and_source():
    latex = r"Đầu. \unknown{Giữ nội dung.}"
    result = HierarchyEngine("2508.02872", 1).parse(latex)
    assert not result.complete
    diagnostic = next(item for item in result.diagnostics if item["code"] == "unhandled_command")
    assert diagnostic["source"] == r"\unknown{Giữ nội dung.}"
    assert diagnostic["offset"] == latex.encode().index(b"\\unknown")


def test_empty_input_returns_empty_lists():
    result = HierarchyEngine("2508.02872", 1).parse("")
    assert result.elements == []
    assert result.hierarchy == []
    assert result.diagnostics == []
    assert result.ordered_children == {}
    assert result.complete


def test_malformed_latex_remains_a_reported_incomplete_result():
    result = HierarchyEngine("2508.02872", 1).parse(r"\section{Unclosed")
    assert not result.complete
    assert any(item["code"] == "invalid_syntax" for item in result.diagnostics)


def test_custom_mapping_is_loaded_once_per_engine(tmp_path):
    mapping = json.loads(DEFAULT_MAPPING.read_text())
    mapping["commands"][r"\customheading"] = {"kind": "section", "level": 2, "content": "title"}
    path = tmp_path / "cấu hình.json"
    path.write_text(json.dumps(mapping), encoding="utf-8")
    engine = HierarchyEngine("2508.02872", 1, path)
    path.write_text("invalid JSON", encoding="utf-8")
    result = engine.parse(r"\customheading{Custom}Body.")
    assert result.complete
    assert any(element.kind == "section" and element.content == "Custom" for element in result.elements)


def test_cpp_exception_restores_python_state(tmp_path):
    mapping = json.loads(DEFAULT_MAPPING.read_text())
    del mapping["sentence"]["abbreviations"]
    path = tmp_path / "invalid_mapping.json"
    path.write_text(json.dumps(mapping))
    engine = HierarchyEngine("2508.02872", 1, path)
    with pytest.raises(ValueError, match="abbreviations"):
        engine.parse("Body.")
    assert HierarchyEngine("2508.02872", 1).parse("Recovered.").complete


def test_cpp_constructor_exceptions_reach_python(tmp_path):
    with pytest.raises(ValueError, match="positive"):
        HierarchyEngine("2508.02872", 0)
    with pytest.raises(RuntimeError, match="Cannot read mapping"):
        HierarchyEngine("2508.02872", 1, tmp_path / "missing.json")
    path = tmp_path / "broken.json"
    path.write_text("{")
    with pytest.raises(ValueError):
        HierarchyEngine("2508.02872", 1, path)


@pytest.mark.parametrize("value", [None, b"Body.", 123])
def test_parse_requires_python_string(value):
    with pytest.raises(TypeError):
        HierarchyEngine("2508.02872", 1).parse(value)


def test_concurrent_calls_on_same_engine_are_independent():
    engine = HierarchyEngine("2508.02872", 1)
    texts = [f"Sentence {number}." for number in range(16)]
    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(engine.parse, texts))
    for text, result in zip(texts, results):
        assert result.complete
        assert [element.content for element in result.elements if element.kind == "sentence"] == [text]


def test_merge_output_can_be_passed_directly_to_engine(tmp_path):
    (tmp_path / "main.tex").write_text(
        r"\documentclass{article}\begin{document}\section{Intro}\input{part}\input{part}\end{document}"
    )
    (tmp_path / "part.tex").write_text("Nội dung.", encoding="utf-8")
    result = HierarchyEngine("2508.02872", 1).parse(merge_latex(tmp_path))
    assert result.complete
    sentence = next(element for element in result.elements if element.kind == "sentence")
    assert sentence.content == "Nội dung."
    section = next(element for element in result.elements if element.kind == "section")
    assert result.ordered_children[section.element_id] == [sentence.element_id, sentence.element_id]


def contents(result, kind):
    return [element.content for element in result.elements if element.kind == kind]


def test_normalization_precedes_ids_and_respects_math_context():
    engine = HierarchyEngine("2508.02872", 1)
    plain = engine.parse(r"\section{Title}Same text.")
    styled = engine.parse(r"\section{\textbf{ Title }\label{s}}\noindent Same \emph{text}\label{x}.")
    assert plain.complete and styled.complete
    assert plain.elements == styled.elements
    result = engine.parse(r"A $\mathbf{x}+\textbf{b}\label{eq}$ value.\begin{equation*}\mathbf{x}\notag\tag{A}\label{e}\end{equation*}")
    assert result.complete
    assert contents(result, "sentence") == [r"A $\mathbf{x}+\textbf{b}$ value."]
    assert contents(result, "formula") == [r"\begin{equation}\mathbf{x}\tag{A}\end{equation}"]


@pytest.mark.parametrize("name,inner,header,argument", [
    ("align", "aligned", "", ""),
    ("align*", "aligned", "", ""),
    ("flalign", "aligned", "", ""),
    ("gather", "gathered", "", ""),
    ("multline*", "gathered", "", ""),
    ("eqnarray", "array", "", "{rcl}"),
    ("alignat", "alignedat", "{2}", "{2}"),
])
def test_multiline_formulas_keep_rows_in_valid_inner_environment(name, inner, header, argument):
    body = r"a&=b\\c&=d"
    result = HierarchyEngine("2508.02872", 1).parse(r"\begin{" + name + "}" + header + body + r"\label{x}\nonumber\end{" + name + "}")
    assert result.complete
    assert contents(result, "formula") == [r"\begin{equation}\begin{" + inner + "}" + argument + body + r"\end{" + inner + r"}\end{equation}"]


def test_transparent_containers_lists_and_named_heading_scopes():
    result = HierarchyEngine("2508.02872", 1).parse(
        r"\section{Body}\begin{proof}[\textbf{Proof sketch}]First.\begin{enumerate}[label=A]\item One.\end{enumerate}\end{proof}"
        r"\begin{acknowledgments}Thanks.\end{acknowledgments}After."
        r"\begin{minipage}[t][2cm][c]{.4\textwidth}Mini.\end{minipage}"
    )
    assert result.complete
    assert set(contents(result, "sentence")) == {"Proof sketch First.", "One.", "Thanks.", "After.", "Mini."}
    assert contents(result, "section") == ["Body", "Acknowledgements"]
    by_content = {element.content: element.element_id for element in result.elements}
    parents = {edge.element_id: edge.parent_id for edge in result.hierarchy}
    assert parents[by_content["Acknowledgements"]] == contents_id(result, "document")
    assert parents[by_content["After."]] == by_content["Body"]
    assert parents[by_content["Thanks."]] == by_content["Acknowledgements"]


def contents_id(result, kind):
    return next(element.element_id for element in result.elements if element.kind == kind)


@pytest.mark.parametrize("name,header", [
    ("verbatim", ""), ("Verbatim", "[fontsize=small]"),
    ("lstlisting", "[language=Python]"), ("minted", "[linenos]{python}"),
])
def test_literal_environment_body_is_exact_and_never_parsed(name, header):
    body = "\n  x  = 1.\n% literal\n\\section{Fake}\n"
    result = HierarchyEngine("2508.02872", 1).parse("Before." + r"\begin{" + name + "}" + header + body + r"\end{" + name + "}After.")
    assert result.complete
    assert contents(result, "section") == []
    assert contents(result, "sentence") == ["Before.", body, "After."]


def test_float_cleanup_consumes_only_declared_placement_arguments():
    result = HierarchyEngine("2508.02872", 1).parse(
        r"\begin{wrapfigure}[12]{r}[1cm]{.4\textwidth}\centering"
        r"\includegraphics[width=.3\textwidth]{plot}\caption[Short]{\textbf{A} plot.}\label{fig:x}\end{wrapfigure}"
        r"\begin{longtable}[c]{lr}\toprule A&B\\\midrule[1pt]C&D\\\bottomrule\end{longtable}"
    )
    assert result.complete
    assert contents(result, "figure") == [
        r"\begin{wrapfigure}{r}{.4\textwidth}\includegraphics[width=.3\textwidth]{plot}\caption[Short]{A plot.}\end{wrapfigure}",
        r"\begin{longtable}{lr} A&B\\C&D\\\end{longtable}",
    ]


def test_inline_environment_math_and_configured_delimiters(tmp_path):
    mapping = json.loads(DEFAULT_MAPPING.read_text())
    mapping["math_delimiters"]["inline"].insert(0, {"open": "@@", "close": "@@", "action": "preserve_in_sentence"})
    path = tmp_path / "mapping.json"
    path.write_text(json.dumps(mapping))
    result = HierarchyEngine("2508.02872", 1, path).parse(r"Use \begin{math}a.b\end{math} and @@c.d@@.")
    assert result.complete
    assert contents(result, "sentence") == ["Use $a.b$ and $c.d$."]


def test_custom_actions_work_without_cpp_tag_overrides(tmp_path):
    mapping = json.loads(DEFAULT_MAPPING.read_text())
    mapping["commands"][r"\plain"] = {"action": "unwrap", "arguments": 1}
    mapping["commands"][r"\drop"] = {"action": "discard", "arguments": 1}
    mapping["environments"]["box"] = {"action": "transparent", "optional_arguments": 1, "optional_argument_content": "prepend"}
    mapping["environments"]["raw"] = {"action": "literal", "kind": "sentence"}
    del mapping["environments"]["abstract"]
    del mapping["environments"]["enumerate"]
    path = tmp_path / "mapping.json"
    path.write_text(json.dumps(mapping))
    engine = HierarchyEngine("2508.02872", 1, path)
    result = engine.parse(r"\begin{box}[Name]\drop{Hidden}\plain{Keep. inside} outside.\end{box}\begin{raw}%\section{Fake}\end{raw}")
    assert result.complete
    assert contents(result, "sentence") == ["Name Keep. inside outside.", r"%\section{Fake}"]
    for name in ("abstract", "enumerate"):
        result = engine.parse(r"\begin{" + name + r"}Hidden.\end{" + name + "}")
        assert not result.complete
        assert contents(result, "section") == []
        assert contents(result, "itemize") == []
        assert result.diagnostics[0]["code"] == "unhandled_environment"


def test_zero_argument_discard_does_not_swallow_following_group():
    result = HierarchyEngine("2508.02872", 1).parse(r"\centering {Visible.} Tail.")
    assert result.complete
    assert "Visible." in " ".join(contents(result, "sentence"))


def test_visible_spaces_inside_unwrapped_arguments_and_inline_verbatim_survive():
    result = HierarchyEngine("2508.02872", 1).parse(r"\textbf{A }word with \emph{ spaces }inside and \verb|a  b.%|.")
    assert result.complete
    assert contents(result, "sentence") == [r"A word with spaces inside and \verb|a  b.%|."]


def test_literals_nested_inside_figures_keep_whitespace_and_comments():
    body = "\n  x  = 1.\n% literal\n"
    result = HierarchyEngine("2508.02872", 1).parse(r"\begin{figure}[t]\begin{verbatim}" + body + r"\end{verbatim}\end{figure}")
    assert result.complete
    assert contents(result, "figure") == [r"\begin{figure}\begin{verbatim}" + body + r"\end{verbatim}\end{figure}"]


@pytest.mark.parametrize("latex", [r"\section{Đầu \unknown{Keep}}Body.", r"Đầu \textbf{A \unknown{Keep} word}.", "Đầu \\textbf{A % comment\n\\unknown{Keep} word}."])
def test_nested_unknown_commands_report_original_utf8_offsets(latex):
    result = HierarchyEngine("2508.02872", 1).parse(latex)
    assert not result.complete
    diagnostic = next(item for item in result.diagnostics if item["code"] == "unhandled_command")
    assert diagnostic["offset"] == latex.encode().index(b"\\unknown")
    assert diagnostic["source"] == r"\unknown{Keep}"


def test_optional_arguments_respect_braced_closing_brackets():
    result = HierarchyEngine("2508.02872", 1).parse(r"\section[Short {]} title]{Real}\begin{proof}[Name {]} here]Body.\end{proof}")
    assert result.complete
    assert contents(result, "section") == ["Real"]
    assert contents(result, "sentence") == ["Name {]} here Body."]


def test_excluded_reference_subtree_does_not_emit_normalization_diagnostics():
    result = HierarchyEngine("2508.02872", 1).parse(r"\section{References}\textbf{\unknown{Hidden}}\section{Acknowledgements}Thanks.")
    assert result.complete
    assert contents(result, "sentence") == ["Thanks."]


@pytest.mark.parametrize("name", ["multicols", "multicols*"])
def test_multicols_keeps_pretext_but_discards_column_geometry(name):
    result = HierarchyEngine("2508.02872", 1).parse(r"\begin{" + name + r"}{2}[\textbf{Visible pretext}][2cm]Body.\end{" + name + "}")
    assert result.complete
    assert contents(result, "sentence") == ["Visible pretext Body."]


def test_layout_wrapper_can_keep_sentence_continuity():
    result = HierarchyEngine("2508.02872", 1).parse(r"One \begin{samepage}continuous\end{samepage} sentence.")
    assert result.complete
    assert contents(result, "sentence") == ["One continuous sentence."]


def test_unfloated_tables_are_atomic_figures():
    result = HierarchyEngine("2508.02872", 1).parse(r"\begin{tabular*}{\textwidth}[t]{lr}A&B\\\end{tabular*}After.")
    assert result.complete
    assert contents(result, "figure") == [r"\begin{tabular*}{\textwidth}{lr}A&B\\\end{tabular*}"]
    assert contents(result, "sentence") == ["After."]
