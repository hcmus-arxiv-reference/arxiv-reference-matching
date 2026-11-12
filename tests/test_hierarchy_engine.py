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
    assert contents(result, "sentence") == ["Name ] here Body."]


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


def test_audit_metadata_layout_and_selected_content_rules():
    result = HierarchyEngine('2508.02872', 1).parse(
        r'\title[Short]{Hidden title}\author{Hidden author}\affiliation{Hidden lab}\maketitle'
        r'\setcounter{page}{1}\pagestyle{plain}\newpage'
        r'\section{\textcolor{red}{Intro}}\IEEEPARstart{W}{e} keep '
        r'\texorpdfstring{printed}{PDF alternative} and \colorbox{blue}{visible}.'
        r'\footnote[2]{A note. Still here} Tail.\\[2pt]Last.'
    )
    assert result.complete, result.diagnostics
    assert contents(result, 'section') == ['Intro']
    assert contents(result, 'sentence') == [
        'We keep printed and visible.', 'A note. Still here Tail.', 'Last.'
    ]


def test_audit_accents_accept_tokens_groups_dotless_letters_and_utf8():
    result = HierarchyEngine('2508.02872', 1).parse(
        r'\section{Caf\'e}\"{o} and \v S and \'{\i} and \c{c} and \AA.'
    )
    assert result.complete, result.diagnostics
    assert contents(result, 'section') == ['Café']
    assert contents(result, 'sentence') == ['ö and Š and í and ç and Å.']


def test_declared_theorem_names_are_local_to_each_parse_and_scope():
    engine = HierarchyEngine('2508.02872', 1)
    result = engine.parse(
        r'\documentclass{article}\newtheorem{thm}{Theorem}[section]'
        r'\newtheorem{lem}[thm]{Lemma}\newtheorem*{fact}{Fact}'
        r'\begin{document}\begin{thm}[Named]Claim.\end{thm}'
        r'\begin{lem}Proof.\end{lem}\begin{fact}Fact.\end{fact}\end{document}'
    )
    assert result.complete, result.diagnostics
    assert contents(result, 'sentence') == ['Named Claim.', 'Proof.', 'Fact.']
    assert not engine.parse(r'\begin{thm}Unregistered.\end{thm}').complete
    scoped = engine.parse(r'{\newtheorem{local}{Local}\begin{local}In.\end{local}}\begin{local}Out.\end{local}')
    assert contents(scoped, 'sentence') == ['In.']
    assert [d['code'] for d in scoped.diagnostics] == ['unhandled_environment']


def test_macro_parameters_defaults_structural_aliases_and_definition_order():
    result = HierarchyEngine('2508.02872', 1).parse(
        r'\documentclass{article}\newcommand{\named}[2][Default]{\textbf{#1}: #2}'
        r'\def\be{\begin{equation}}\def\ee{\end{equation}}'
        r'\newcommand{\sect}[1]{\section{#1}}\begin{document}'
        r'\sect{Intro}\named{One}. \named[Other]{Two}. \be x=1\ee'
        r'\renewcommand{\named}[1]{Changed #1}\named{Three}.\end{document}'
    )
    assert result.complete, result.diagnostics
    assert contents(result, 'section') == ['Intro']
    assert contents(result, 'sentence') == ['Default: One.', 'Other: Two.', 'Changed Three.']
    assert contents(result, 'formula') == [r'\begin{equation}x=1\end{equation}']


def test_macro_scope_conditionals_and_literal_protection():
    engine = HierarchyEngine('2508.02872', 1)
    result = engine.parse(
        r'\newcommand{\word}{Outer}\iffalse\renewcommand{\word}{Hidden}\fi'
        r'\word. {\renewcommand{\word}{Inner}\word.} \word.'
        r'\begin{verbatim}\word % unchanged\end{verbatim}'
    )
    assert result.complete, result.diagnostics
    assert contents(result, 'sentence') == ['Outer.', 'Inner.', r'\word % unchanged']
    root = next(e for e in result.elements if e.kind == 'document')
    assert len(result.ordered_children[root.element_id]) == 4  # repeated Outer is deduplicated
    assert not engine.parse(r'\word.').complete


@pytest.mark.parametrize('definition', [r'\def\bad{\bad}', r'\newcommand{\bad}{\ensuremath{\bad}}'])
def test_recursive_macros_stop_with_a_diagnostic(definition):
    result = HierarchyEngine('2508.02872', 1).parse(definition + r'\bad')
    assert not result.complete
    assert any(d['code'] == 'invalid_syntax' and ('limit' in d['message'] or '128' in d['message']) for d in result.diagnostics)


def test_expanded_offsets_refer_to_original_utf8_source():
    latex = r'\newcommand{\word}{A longer replacement}\word. Đầu. \unknown{Keep}'
    result = HierarchyEngine('2508.02872', 1).parse(latex)
    diagnostic = next(d for d in result.diagnostics if d['code'] == 'unhandled_command')
    assert diagnostic['offset'] == latex.encode().index(b'\\unknown')
    latex = r'\newcommand{\word}{\unknown{Inside}}Đầu. \section{\word}'
    result = HierarchyEngine('2508.02872', 1).parse(latex)
    assert result.diagnostics[0]['offset'] == latex.encode().rindex(b'\\word')


def test_unsupported_macro_parameters_remain_diagnostic_and_shadow_builtin():
    result = HierarchyEngine('2508.02872', 1).parse(r'\def\textbf#1;{Hidden}\textbf{Visible}')
    assert not result.complete
    assert [d['code'] for d in result.diagnostics] == ['unexpanded_definition', 'unhandled_command']
    assert r'\textbf{Visible}' in contents(result, 'sentence')


def test_audit_wrappers_keep_keywords_and_appendices_after_references():
    result = HierarchyEngine('2508.02872', 1).parse(
        r'\begin{frontmatter}\abstract{Summary.}\begin{IEEEkeywords}alpha, beta\end{IEEEkeywords}\end{frontmatter}'
        r'\section{References}Hidden.\begin{appendices}\section{Details}Keep.\end{appendices}'
        r'\begin{CCSXML}<xml>Hidden.</xml>\end{CCSXML}'
    )
    assert result.complete, result.diagnostics
    assert contents(result, 'section') == ['Abstract', 'Details']
    assert contents(result, 'sentence') == ['Summary.', 'alpha, beta', 'Keep.']


def test_token_length_arguments_do_not_truncate_a_figure():
    result = HierarchyEngine('2508.02872', 1).parse(
        r'\begin{table}\setlength\tabcolsep{3pt}\textbf A\end{table}After.'
    )
    assert result.complete, result.diagnostics
    assert contents(result, 'figure') == [r'\begin{table}A\end{table}']
    assert contents(result, 'sentence') == ['After.']


def test_macros_can_leave_references_and_conditional_preamble_is_not_guessed():
    result = HierarchyEngine('2508.02872', 1).parse(
        r'\documentclass{article}\newcommand{\append}{\appendix\section{Extra}}'
        r'\ifdefined\missing\def\choice{Wrong one}\else\def\choice{Wrong two}\fi'
        r'\begin{document}\section{References}Hidden.\append Kept. \choice\end{document}'
    )
    assert contents(result, 'section') == ['Extra']
    assert contents(result, 'sentence') == ['Kept.', r'\choice']
    assert [d['code'] for d in result.diagnostics] == ['unhandled_command']


def test_unclosed_source_group_keeps_parsed_content_and_reports_location():
    latex = 'Đầu. {Tail.'
    result = HierarchyEngine('2508.02872', 1).parse(latex)
    assert contents(result, 'sentence') == ['Đầu.', 'Tail.']
    assert result.diagnostics[0]['code'] == 'invalid_syntax'
    assert result.diagnostics[0]['offset'] == latex.encode().index(b'{')


def test_newif_declaration_and_local_switches_select_actual_branch():
    result = HierarchyEngine('2508.02872', 1).parse(
        r'\documentclass{article}\newif\ifshow\showfalse'
        r'\ifshow\newcommand{\word}{Hidden}\else\newcommand{\word}{Visible}\fi'
        r'\begin{document}\word. {\showtrue\ifshow Local.\fi}'
        r'\ifshow Hidden.\else Outer.\fi\end{document}'
    )
    assert result.complete, result.diagnostics
    assert contents(result, 'sentence') == ['Visible.', 'Local.', 'Outer.']


def test_nested_macro_expansion_consumes_following_arguments_and_formula_end():
    result = HierarchyEngine('2508.02872', 1).parse(
        r'\newcommand{\red}{\textcolor{red}}\def\be{\begin{equation}}\def\ee{\end{equation}}'
        r'\section{\red{Title}}Body\footnote{Before \be x=1\ee After.} End.'
    )
    assert result.complete, result.diagnostics
    assert contents(result, 'section') == ['Title']
    assert contents(result, 'sentence') == ['Body Before', 'After. End.']
    assert contents(result, 'formula') == [r'\begin{equation}x=1\end{equation}']


def test_tikz_loop_variables_are_opaque_inside_atomic_figures():
    body = r'\foreach \i/\label in {1/a,2/b} \node {$\label$};'
    result = HierarchyEngine('2508.02872', 1).parse(
        r'\def\i#1{#1}\begin{figure}\begin{tikzpicture}' + body + r'\end{tikzpicture}\end{figure}After.'
    )
    assert result.complete, result.diagnostics
    assert contents(result, 'figure') == [r'\begin{figure}\begin{tikzpicture}' + body + r'\end{tikzpicture}\end{figure}']
    assert contents(result, 'sentence') == ['After.']


def test_mathpalette_callback_is_preserved_without_guessing_implicit_parameters():
    result = HierarchyEngine('2508.02872', 1).parse(
        r'\newcommand{\raise}[3]{#1#2#3}\newcommand{\special}[1]{\mathpalette{\raise{#1}}}'
        r'\begin{equation}\special{2pt}{x}\end{equation}After.'
    )
    assert result.complete, result.diagnostics
    assert contents(result, 'formula') == [r'\begin{equation}\mathpalette{\raise{2pt}}{x}\end{equation}']
    assert contents(result, 'sentence') == ['After.']


def test_unknown_escaped_unicode_command_keeps_valid_utf8_diagnostic():
    result = HierarchyEngine('2508.02872', 1).parse('Đầu. \\ Tail.')
    assert not result.complete
    assert result.diagnostics[0]['source'] == '\\\u00a0'


def test_unknown_command_inside_accent_is_reported_at_original_offset():
    latex = r"Đầu. \'{\unknown}"
    result = HierarchyEngine('2508.02872', 1).parse(latex)
    assert not result.complete
    assert result.diagnostics[0]['offset'] == latex.encode().index(b'\\unknown')


def test_macros_in_math_inside_figures_remain_opaque():
    result = HierarchyEngine('2508.02872', 1).parse(
        r'\newcommand{\callback}[3]{#1#2#3}'
        r'\begin{figure}$\callback{x}$\end{figure}After.'
    )
    assert result.complete, result.diagnostics
    assert contents(result, 'figure') == [r'\begin{figure}$\callback{x}$\end{figure}']
    assert contents(result, 'sentence') == ['After.']


def test_macro_expansion_preserves_control_word_token_boundaries():
    result = HierarchyEngine('2508.02872', 1).parse(
        r'\def\symbol{\alpha}\def\tail{b}\newcommand{\parameter}[1]{\alpha#1}'
        r'$\symbol\tail$ and $\parameter{b}$. '
        r'\def\name{Coffee}\def\prefix{\xspace}\section{\prefix\name{} title}'
    )
    assert result.complete, result.diagnostics
    assert contents(result, 'sentence') == [r'$\alpha b$ and $\alpha b$.']
    assert contents(result, 'section') == ['Coffee title']


def test_xspace_respects_punctuation_and_empty_groups():
    result = HierarchyEngine('2508.02872', 1).parse(
        r'\newcommand{\name}{Model\xspace}\section{\name{} title}'
        r'\name, \name{}! \name\textbf{works}.'
    )
    assert result.complete, result.diagnostics
    assert contents(result, 'section') == ['Model title']
    assert contents(result, 'sentence') == ['Model, Model! Model works.']


def test_xspace_does_not_insert_gap_in_hyphenated_or_slash_names():
    result = HierarchyEngine('2508.02872', 1).parse(
        r'\newcommand{\acd}{ACD\xspace}\section{\acd-train / \acd-val / \acd/test}'
        r'Use \acd-train and \acd/test.'
    )
    assert result.complete, result.diagnostics
    assert contents(result, 'section') == ['ACD-train / ACD-val / ACD/test']
    assert contents(result, 'sentence') == ['Use ACD-train and ACD/test.']


def test_grouping_braces_normalize_consistently_without_dropping_visible_braces():
    engine = HierarchyEngine('2508.02872', 1)
    plain = engine.parse(r'\section{Title}Bold.')
    grouped = engine.parse(r'\section{{Title}}\textbf{{Bold}}.')
    assert grouped.complete, grouped.diagnostics
    assert grouped.elements == plain.elements
    result = engine.parse(r'\section{\{Visible\}}\textbf{{A \{set\} and $\{x\}$}}.')
    assert result.complete, result.diagnostics
    assert contents(result, 'section') == [r'\{Visible\}']
    assert contents(result, 'sentence') == [r'A \{set\} and $\{x\}$.']


@pytest.mark.parametrize('definition', [r'\newcommand{\term}{Dr. Smith}', r'\newcommand{\term}[1]{#1}'])
def test_macro_expansion_preserves_command_sentence_protection(definition):
    call = r'\term' if '[1]' not in definition else r'\term{Dr. Smith}'
    result = HierarchyEngine('2508.02872', 1).parse(definition + call + ' works. Next.')
    assert result.complete, result.diagnostics
    assert contents(result, 'sentence') == ['Dr. Smith works.', 'Next.']


def test_protected_macro_text_still_creates_structural_nodes():
    result = HierarchyEngine('2508.02872', 1).parse(
        r'\newcommand{\body}{\section{Intro}One. Two. $$x=1$$\begin{itemize}\item Item.\end{itemize}}'
        r'\body Outside.'
    )
    assert result.complete, result.diagnostics
    assert contents(result, 'section') == ['Intro']
    assert contents(result, 'sentence') == ['One. Two.', 'Item.', 'Outside.']
    assert contents(result, 'formula') == [r'\begin{equation}x=1\end{equation}']
    assert len(contents(result, 'item')) == 1


@pytest.mark.parametrize('wrapper', [False, True])
def test_malformed_suffix_keeps_valid_prefix_and_error_location(wrapper):
    body = r'Đầu. Another complete sentence. \section{Broken'
    source = r'\documentclass{article}\begin{document}' + body if wrapper else body
    result = HierarchyEngine('2508.02872', 1).parse(source)
    assert not result.complete
    assert contents(result, 'sentence') == ['Đầu.', 'Another complete sentence.']
    assert result.diagnostics[0]['code'] == 'invalid_syntax'
    assert result.diagnostics[0]['offset'] >= source.encode().index(b'\\section')


def test_nested_inline_delimiters_inside_braced_arguments_do_not_close_outer_math():
    result = HierarchyEngine('2508.02872', 1).parse(
        r'\begin{document}\(x\footnote{note \(y\)}+z\). Tail.\end{document}'
    )
    assert result.complete, result.diagnostics
    assert contents(result, 'sentence') == [r'$x\footnote{note \(y\)}+z$.', 'Tail.']
    result = HierarchyEngine('2508.02872', 1).parse(r'$x+\text{cost $y$}$. Tail.')
    assert result.complete, result.diagnostics
    assert contents(result, 'sentence') == [r'$x+\text{cost $y$}$.', 'Tail.']


def test_math_delimiter_scan_respects_groups_comments_and_escaped_braces():
    result = HierarchyEngine('2508.02872', 1).parse('$x+{y}% ignore $\n+\\{z\\}$. Tail.')
    assert result.complete, result.diagnostics
    assert contents(result, 'sentence') == [r'$x+{y}+\{z\}$.', 'Tail.']
    assert not HierarchyEngine('2508.02872', 1).parse('$x+{unclosed$').complete


def test_unwrap_stream_extracts_block_formulas_in_source_order_and_parent():
    result = HierarchyEngine('2508.02872', 1).parse(
        r'\section{Intro}\textbf{Before $$x=1$$ After.} Tail.'
        r'\section{Next}Final.'
    )
    assert result.complete, result.diagnostics
    assert contents(result, 'sentence') == ['Before', 'After. Tail.', 'Final.']
    formula = next(e for e in result.elements if e.kind == 'formula')
    assert formula.content == r'\begin{equation}x=1\end{equation}'
    section = next(e for e in result.elements if e.kind == 'section' and e.content == 'Intro')
    assert next(h.parent_id for h in result.hierarchy if h.element_id == formula.element_id) == section.element_id
    nodes = {e.element_id: e for e in result.elements}
    assert [nodes[k].kind for k in result.ordered_children[section.element_id]] == ['sentence', 'formula', 'sentence']


def test_unwrap_stream_handles_nested_wrappers_macros_scope_and_punctuation():
    result = HierarchyEngine('2508.02872', 1).parse(
        r'\newcommand{\name}{Outer\xspace}\def\be{\begin{equation}}\def\ee{\end{equation}}'
        r'\textbf{\renewcommand{\name}{Inner\xspace}\emph{\name}-train \be x=1\ee}'
        r'\name/test.\begin{itemize}\item\textcolor{red}{Keep. inside} End.\end{itemize}'
    )
    assert result.complete, result.diagnostics
    assert contents(result, 'sentence') == ['Inner-train', 'Outer/test.', 'Keep. inside End.']
    assert contents(result, 'formula') == [r'\begin{equation}x=1\end{equation}']


def test_unwrap_stream_keeps_utf8_offsets_after_splicing_and_comments():
    source = 'Đầu. \\textcolor{red}{A % comment\n\\unknown{Inside}} Tail. \\unknown{After}'
    result = HierarchyEngine('2508.02872', 1).parse(source)
    diagnostics = [d for d in result.diagnostics if d['code'] == 'unhandled_command']
    assert [d['offset'] for d in diagnostics] == [source.encode().index(b'\\unknown'), source.encode().rindex(b'\\unknown')]
    assert contents(result, 'sentence') == ['Đầu.', r'A \unknown{Inside} Tail.', r'\unknown{After}']


def test_abstract_command_body_streams_formulas_and_keeps_body_boundary():
    result = HierarchyEngine('2508.02872', 1).parse(r'\abstract{Before $$x=1$$ After.}Tail.')
    assert result.complete, result.diagnostics
    assert contents(result, 'section') == ['Abstract']
    assert contents(result, 'sentence') == ['Before', 'After.', 'Tail.']
    assert contents(result, 'formula') == [r'\begin{equation}x=1\end{equation}']


def test_streaming_unwrap_works_without_macro_declaration_configuration(tmp_path):
    mapping = json.loads(DEFAULT_MAPPING.read_text())
    del mapping['declarations']
    path = tmp_path / 'mapping.json'
    path.write_text(json.dumps(mapping))
    result = HierarchyEngine('2508.02872', 1, path).parse(r'\textbf{Before $$x=1$$ After.} Tail.')
    assert result.complete, result.diagnostics
    assert contents(result, 'sentence') == ['Before', 'After. Tail.']
    assert contents(result, 'formula') == [r'\begin{equation}x=1\end{equation}']


@pytest.mark.parametrize('outer', [False, True])
def test_tabular_column_preamble_is_not_scanned_as_standalone_math(outer):
    table = r'\begin{tabular}{>{$}l<{$\hspace{12pt}}c}A&B\\\end{tabular}'
    source = (r'\begin{figure}' + table + r'\end{figure}' if outer else table) + 'Tail.'
    result = HierarchyEngine('2508.02872', 1).parse(source)
    assert result.complete, result.diagnostics
    assert r'{>{$}l<{$\hspace{12pt}}c}' in contents(result, 'figure')[0]
    assert contents(result, 'sentence') == ['Tail.']


def test_isolated_heading_token_inside_wrapper_reports_limitation_without_losing_suffix():
    result = HierarchyEngine('2508.02872', 1).parse(r'Before. \keywords\section{Introduction}Keep. \section{Next}Tail.')
    assert not result.complete
    assert [d['code'] for d in result.diagnostics] == ['unhandled_command']
    assert result.diagnostics[0]['source'] == r'\keywords\section'
    assert contents(result, 'section') == ['Next']
    assert contents(result, 'sentence')[-1] == 'Tail.'
    assert any('Introduction' in s and 'Keep.' in s for s in contents(result, 'sentence'))
