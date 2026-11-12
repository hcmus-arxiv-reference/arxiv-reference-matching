"""Synthetic source trees: no downloaded TeX is committed."""
from pathlib import Path

import pytest

from src.parse.source import assemble_source
from src.crawl.source import ArxivSourceDownloader
from src.crawl.http_client import HttpResponse


def tree(tmp_path, files):
    for name, text in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return tmp_path


def test_nested_input_provenance_unused_and_repeated_inclusion(tmp_path):
    root = tree(tmp_path, {
        "main.tex": r"\documentclass{article}A\input{parts/one}B\input{parts/one}\end{document}\input{missing}",
        "parts/one.tex": r"ONE\input{two}",
        "parts/two.tex": "TWO",
        "unused.tex": "UNUSED",
    })
    result = assemble_source(root)
    assert result.status == "ready"
    assert result.text == r"\documentclass{article}AONETWOBONETWO\end{document}"
    assert result.files == ["main.tex", "parts/one.tex", "parts/two.tex"]
    assert result.unused_tex_files == ["unused.tex"]
    assert len(result.includes) == 4
    assert result.spans[0].output_start == 0
    assert result.spans[-1].output_end == len(result.text)
    for previous, current in zip(result.spans, result.spans[1:]):
        assert previous.output_end == current.output_start
    for span in result.spans:
        text = (root / span.file).read_text()
        assert result.text[span.output_start:span.output_end] == text[span.source_start:span.source_end]
        assert span.line == text.count("\n", 0, span.source_start) + 1
    assert result.to_dict() == assemble_source(root).to_dict()


def test_comments_escaped_percent_verbatim_and_definitions(tmp_path):
    source = r"""% \documentclass{fake} \input{not_real}
\newcommand{\example}{\documentclass{fake}}
\documentclass{article}
% \input{absent}
\verb|\input{absent}|
\begin{verbatim}\input{absent}\end{verbatim}
\begin{comment}\input{absent}\end{comment}
Escaped \% \input{yes}
Escaped backslash \\% \input{absent}
"""
    result = assemble_source(tree(tmp_path, {"main.tex": source, "yes.tex": "YES"}))
    assert result.status == "needs_review"  # root declared in macro body: explicit diagnostic
    assert result.files == ["main.tex", "yes.tex"]
    assert len(result.includes) == 1
    assert "Escaped \\% YES" in result.text


def test_literal_conditionals_and_includeonly(tmp_path):
    source = r"""\documentclass{article}
\iffalse\input{absent}\iftrue\input{absent}\fi\else\input{yes}\fi
\includeonly{kept}
\include{excluded}\include{kept}\input{not_an_include}
"""
    result = assemble_source(tree(tmp_path, {"main.tex": source, "yes.tex": "YES",
                                            "kept.tex": "KEPT", "not_an_include.tex": "INPUT"}))
    assert result.status == "ready"
    assert result.files == ["main.tex", "yes.tex", "kept.tex", "not_an_include.tex"]
    assert any(i["status"] == "excluded_by_includeonly" for i in result.includes)


def test_unknown_conditionals_are_reported_without_guessing_branch(tmp_path):
    source = r"\documentclass{article}\newif\ifdraft\ifdraft\input{missing}\else\input{other}\fi\input{yes}"
    result = assemble_source(tree(tmp_path, {"main.tex": source, "yes.tex": "YES"}))
    assert result.status == "needs_review"
    assert result.files == ["main.tex", "yes.tex"]
    assert [i.code for i in result.issues] == ["unsupported_conditional"]


@pytest.mark.parametrize("name,body", [
    ("missing", r"\input{absent}"),
    ("cycle", r"\input{main}"),
    ("escape", r"\input{../outside}"),
    ("absolute", r"\input{/etc/passwd}"),
    ("dynamic", r"\input{\filename}"),
    ("bad_group", r"\input{broken"),
])
def test_invalid_sources_are_not_silently_successful(tmp_path, name, body):
    result = assemble_source(tree(tmp_path, {"main.tex": r"\documentclass{article}" + body}))
    assert result.status == "error", name
    assert any(i.severity == "error" for i in result.issues)


def test_roots_need_disambiguation_and_explicit_root_is_validated(tmp_path):
    root = tree(tmp_path, {"a.tex": r"\documentclass{article}A", "b.tex": r"\documentclass{article}B"})
    assert assemble_source(root).issues[0].code == "ambiguous_root"
    assert assemble_source(root, root_file="b.tex").text.endswith("B")
    assert assemble_source(root, root_file="../outside.tex").status == "error"
    (root / "a.tex").unlink(); (root / "b.tex").write_text("No document class")
    assert assemble_source(root).issues[0].code == "missing_root"


def test_macro_body_and_let_are_not_executed(tmp_path):
    source = r"\documentclass{article}\def\part#1{\input{#1}}\newcommand{\load}[1]{\input{#1}}\let\fetch=\input\part{absent}"
    result = assemble_source(tree(tmp_path, {"main.tex": source}))
    assert result.status == "needs_review"
    assert not result.includes
    assert len(result.issues) == 3


def test_input_without_braces_and_comment_in_argument(tmp_path):
    root = tree(tmp_path, {"main.tex": "\\documentclass{article}\n\\input one\n\\input{% comment\ntwo}\n",
                           "one.tex": "ONE", "two.tex": "TWO"})
    result = assemble_source(root)
    assert result.status == "ready"
    assert result.text.endswith("ONE\nTWO\n")


def test_root_working_directory_takes_precedence(tmp_path):
    result = assemble_source(tree(tmp_path, {
        "main.tex": r"\documentclass{article}\input{parts/one}",
        "parts/one.tex": r"\input{two}", "two.tex": "CORRECT", "parts/two.tex": "WRONG",
    }))
    assert result.status == "ready"
    assert result.text.endswith("CORRECT")
    assert "parts/two.tex" in result.unused_tex_files


def test_endinput_and_child_end_document(tmp_path):
    source = r"\documentclass{article}\input{one}TAIL\input{two}AFTER"
    root = tree(tmp_path, {"main.tex": source, "one.tex": "ONE\\endinput\n\\input{missing}",
                           "two.tex": r"TWO\end{document}\input{missing}"})
    result = assemble_source(root)
    assert result.status == "ready"
    assert result.text == r"\documentclass{article}ONETAILTWO\end{document}"


@pytest.mark.parametrize("control", [r"\renewcommand{\input}[1]{}",
                                     r"\def\input#1{}", r"\includeonly{\chosen}",
                                     r"\endinput\input{missing}",
                                     r"\AtBeginDocument{\input{part}}"])
def test_compilation_command_redefinitions_and_dynamic_filters_are_flagged(tmp_path, control):
    result = assemble_source(tree(tmp_path, {"main.tex": r"\documentclass{article}" + control}))
    assert result.status in {"needs_review", "error"}


@pytest.mark.parametrize("body", [
    r"\AtBeginDocument{\providecommand\BibTeX{{Bib\TeX}}}",
    r"\AtEndDocument{\fancyfoot[L]{Preprint}}",
    r"\ifdefined\draft\newcommand{\name}{Draft}\else\newcommand{\name}{Final}\fi",
    r"\if@double@blind@\newcommand{\link}[1]{Hidden}\else\newcommand{\link}[1]{\url{#1}}\fi",
    r"\ifbool{draft}{\textbf{Draft}}{Final}",
    r"\ifthenelse{\equal{a}{b}}{One}{Two}",
    r"\IfFileExists{optional.sty}{\usepackage{optional}}{}",
    r"\ifcsname labelindent\endcsname\let\labelindent\relax\fi",
    r"$A\iff B$",
    r"\newcount\n\n=0\loop\ifnum\n<100\advance\n by1\def\row{Text}\repeat",
])
def test_non_path_controls_do_not_block_gathering(tmp_path, body):
    result = assemble_source(tree(tmp_path, {
        "main.tex": r"\documentclass{article}" + body + r"\input{part}", "part.tex": "BODY",
    }))
    assert result.status == "ready", result.issues
    assert result.files == ["main.tex", "part.tex"]
    assert result.text.endswith("BODY")


@pytest.mark.parametrize("body", [
    r"\ifbool{draft}{\input{one}}{\input{two}}",
    r"\ifstrequal{a}{b}{Nothing}{\input{one}}",
    r"\IfFileExists{one.tex}{\input{one}}{}",
    r"\ifdefined\draft\input{one}\else\input{two}\fi",
    r"\loop\ifnum\n<2\input{one}\advance\n by1\repeat",
    r"\ifdraft\let\input\relax\fi",
    r"\ifdraft\def\input#1{}\fi",
])
def test_controls_that_can_change_includes_still_require_review(tmp_path, body):
    result = assemble_source(tree(tmp_path, {
        "main.tex": r"\documentclass{article}" + body + r"\input{part}",
        "part.tex": "BODY", "one.tex": "ONE", "two.tex": "TWO",
    }))
    assert result.status == "needs_review"
    assert result.files == ["main.tex", "part.tex"]
    assert not any(issue.code == "unclosed_conditional" for issue in result.issues)


def test_lstinline_options_and_braced_content_are_not_real_includes(tmp_path):
    result = assemble_source(tree(tmp_path, {
        "main.tex": (r"\documentclass{article}\lstinline[style=python]{x = '\input{missing}'}"
                     r"\lstinline[language=tex]|\input{missing}|\input{part}"),
        "part.tex": "BODY",
    }))
    assert result.status == "ready"
    assert result.files == ["main.tex", "part.tex"]


@pytest.mark.parametrize("argument,filename", [
    ('"./part.tex"', "part.tex"),
    ('"part name"', "part name.tex"),
    ("0.abstract", "0.abstract.tex"),
    ("plot.beta_0.5", "plot.beta_0.5.tex"),
])
def test_quoted_and_dotted_input_names_resolve(tmp_path, argument, filename):
    result = assemble_source(tree(tmp_path, {
        "main.tex": r"\documentclass{article}\input{" + argument + "}", filename: "BODY",
    }))
    assert result.status == "ready", result.issues
    assert result.text == r"\documentclass{article}BODY"
    assert result.files == ["main.tex", filename]


def test_unbraced_quoted_input_can_contain_spaces(tmp_path):
    result = assemble_source(tree(tmp_path, {
        "main.tex": '\\documentclass{article}\\input "part name"\n', "part name.tex": "BODY",
    }))
    assert result.status == "ready"
    assert result.text == "\\documentclass{article}BODY\n"


def test_symlink_is_rejected(tmp_path):
    root = tree(tmp_path / "source", {"main.tex": r"\documentclass{article}\input{linked}"})
    outside = tmp_path / "outside.tex"; outside.write_text("SECRET")
    (root / "linked.tex").symlink_to(outside)
    result = assemble_source(root)
    assert result.status == "error"
    assert "SECRET" not in result.text


def test_expansion_budget_and_depth_bound(tmp_path):
    root = tree(tmp_path, {"main.tex": r"\documentclass{article}\input{one}\input{one}", "one.tex": "X" * 50})
    assert assemble_source(root, max_chars=100).status == "error"
    assert assemble_source(root, max_depth=1).status == "error"


def test_non_utf8_is_visible_warning(tmp_path):
    (tmp_path / "main.tex").write_bytes(b"\\documentclass{article}\nCaf\xe9")
    result = assemble_source(tmp_path)
    assert result.status == "needs_review"
    assert result.issues[0].code == "encoding_fallback"


def test_receipt_required_and_no_tex_distinguished_from_missing(tmp_path):
    root = tree(tmp_path / "unverified", {"main.tex": r"\documentclass{article}"})
    assert assemble_source(root, require_receipt=True).issues[0].code == "invalid_receipt"

    class Client:
        def get(self, url, **_options):
            return HttpResponse(200, {}, b"%PDF-1.7 synthetic")

    source = ArxivSourceDownloader(Client(), tmp_path / "raw").download("2508.02872", 1)
    result = assemble_source(source.path, require_receipt=True)
    assert result.status == "empty_non_tex" and not result.files and result.text == ""
    (source.path / "rogue.tex").write_text(r"\documentclass{article}")
    assert assemble_source(source.path, require_receipt=True).status == "error"
