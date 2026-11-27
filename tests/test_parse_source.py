"""Synthetic source trees: no downloaded TeX is committed."""
from pathlib import Path
import json

import pytest

from src.parse.source import assemble_source
from src.crawl.source import ArxivSourceDownloader
from src.crawl.http_client import HttpResponse


def tree(tmp_path, files):
    for name, text in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))
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


def test_ifthenelse_resumes_after_both_braced_alternatives(tmp_path):
    source = (r"\documentclass{article}\begin{document}\iftrue"
              r"\ifthenelse{\equal{a}{b}}{\input{missing}}{\input{other}}\fi"
              r"\input{yes}\end{document}")
    result = assemble_source(tree(tmp_path, {"main.tex": source, "yes.tex": "YES"}))
    assert result.status == "needs_review"
    assert [i.code for i in result.issues] == ["unsupported_conditional"]
    assert result.files == ["main.tex", "yes.tex"]
    assert result.text.endswith(r"YES\end{document}")


@pytest.mark.parametrize("condition,expected", [
    (r"\ifnum -2<1\relax", "yes.tex"), (r"\ifnum 10=2 ", "no.tex"),
    (r"\ifnum 1>0\more ", None),
])
def test_literal_integer_comparison(tmp_path, condition, expected):
    source = r"\documentclass{article}" + condition + r"\input{yes}\else\input{no}\fi"
    result = assemble_source(tree(tmp_path, {"main.tex": source, "yes.tex": "Y", "no.tex": "N"}))
    if expected:
        assert result.status == "ready"
        assert result.files == ["main.tex", expected]
    else:
        assert result.status == "needs_review"
        assert result.files == ["main.tex"]


# A missing \input is a warning, not an error: see
# test_missing_input_is_a_warning_and_the_version_still_assembles.
@pytest.mark.parametrize("name,body", [
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
                                     r"\AtBeginDocument{\input{deferred}}"])
def test_compilation_command_redefinitions_and_dynamic_filters_are_flagged(tmp_path, control):
    result = assemble_source(tree(tmp_path, {"main.tex": r"\documentclass{article}" + control}))
    assert result.status in {"needs_review", "error"}


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


@pytest.mark.parametrize("body", [
    r"$a \iff b$\input{yes}",
    r"\AtBeginDocument{\fancyfoot[L]{Preprint}}\input{yes}",
    "\\AtBeginDocument{% \\input{ignored}\n}\\input{yes}",
    r"\newif\ifdraft\newcommand{\choice}{\ifdraft A\else B\fi}\input{yes}",
    r"\def\choice{\ifmmode A\else B\fi}\input{yes}",
])
def test_issue30_math_hooks_and_macro_conditions(tmp_path, body):
    result = assemble_source(tree(tmp_path, {
        "main.tex": r"\documentclass{article}" + body, "yes.tex": "YES",
    }))
    assert result.status == "ready"
    assert result.files == ["main.tex", "yes.tex"]
    assert result.text.endswith("YES")


@pytest.mark.parametrize("body", [
    r"\input{later}", r"\InputIfFileExists{later.tex}{}{}",
    r"\import{parts/}{later.tex}", r"\catcode`\@=11",
])
def test_deferred_input_is_not_expanded_early(tmp_path, body):
    result = assemble_source(tree(tmp_path, {
        "main.tex": r"\documentclass{article}\AtBeginDocument{" + body + "}",
        "later.tex": "DEFERRED",
    }))
    assert result.status == "needs_review"
    assert result.files == ["main.tex"]
    assert not result.includes


def test_missing_bbl_is_preserved_as_warning(tmp_path):
    result = assemble_source(tree(tmp_path, {
        "main.tex": r"\documentclass{article}\input{refs.bbl}\input{yes}",
        "yes.tex": "YES",
    }))
    assert result.status == "needs_review"
    assert [issue.code for issue in result.issues] == ["missing_bbl"]
    assert result.includes[0]["status"] == "missing_bbl"
    assert result.text.endswith(r"\input{refs.bbl}YES")


def test_bbl_path_escape_still_fails(tmp_path):
    result = assemble_source(tree(tmp_path, {
        "main.tex": r"\documentclass{article}\input{../refs.bbl}",
    }))
    assert result.status == "error"


def test_multiple_roots_choose_only_complete_document(tmp_path):
    root = tree(tmp_path, {
        "main.tex": r"\documentclass{article}\begin{document}BODY\end{document}",
        "template.tex": r"\documentclass{article}% \\begin{document}",
    })
    result = assemble_source(root)
    assert result.status == "ready"
    assert result.root == "main.tex"
    assert result.unused_tex_files == ["template.tex"]
    assert result.to_dict() == assemble_source(root).to_dict()


def test_two_complete_roots_remain_ambiguous(tmp_path):
    body = r"\documentclass{article}\begin{document}BODY\end{document}"
    result = assemble_source(tree(tmp_path, {"a.tex": body, "b.tex": body}))
    assert result.status == "error"
    assert result.issues[0].code == "ambiguous_root"


def test_standalone_diagram_and_single_article_root(tmp_path):
    document = r"\begin{document}BODY\end{document}"
    files = {"diagrams/map.tex": r"\documentclass[tikz]{standalone}" + document,
             "submission.tex": r"\documentclass{article}" + document}
    result = assemble_source(tree(tmp_path, files))
    assert (result.status, result.root) == ("ready", "submission.tex")
    files["supp.tex"] = r"\documentclass{article}" + document
    assert assemble_source(tree(tmp_path, files)).issues[0].code == "ambiguous_root"


def test_root_with_document_in_input_is_not_discarded(tmp_path):
    result = assemble_source(tree(tmp_path, {
        "main.tex": r"\documentclass{article}\input{body}",
        "body.tex": r"\begin{document}MAIN\end{document}",
        "supplement.tex": r"\documentclass{article}\begin{document}SUPPLEMENT\end{document}",
    }))
    # The complete-document shortcut must not pick supplement.tex; the name rule
    # (ADR 0005) picks main.tex instead.
    assert result.root == "main.tex" and "MAIN" in result.text
    assert "root_selected_by_name" in [i.code for i in result.issues]


def test_root_with_document_in_input_stays_ambiguous_without_evidence(tmp_path):
    result = assemble_source(tree(tmp_path, {
        "main.tex": r"\documentclass{article}\input{body}",
        "body.tex": r"\begin{document}MAIN\end{document}",
        "other.tex": r"\documentclass{article}\begin{document}OTHER\end{document}",
    }))
    assert result.status == "error"
    assert result.issues[0].code == "ambiguous_root"


def test_present_bbl_outside_tex_inventory_is_not_reported_missing(tmp_path):
    result = assemble_source(tree(tmp_path, {
        "main.tex": r"\documentclass{article}\input{refs.bbl}",
        "refs.bbl": r"\bibitem{one} Author. Title.",
    }))
    assert result.status == "error"
    assert [issue.code for issue in result.issues] == ["include_error"]


def test_dotted_input_stem_matches_tex_only_when_literal_file_absent(tmp_path):
    files = {"main.tex": r"\documentclass{article}\input{sec.2}", "sec.2.tex": "Body"}
    result = assemble_source(tree(tmp_path, files))
    assert result.status == "ready"
    assert result.files == ["main.tex", "sec.2.tex"]
    (tmp_path / "sec.2").write_bytes(b"other content")
    assert assemble_source(tmp_path).issues[0].code == "include_error"


@pytest.mark.parametrize("case", [
    "multi-file-input", "comments-and-verbatim", "levels-skip", "appendix-ack-refs",
])
def test_source_golden(case, tmp_path):
    fixture = Path(__file__).parent / "fixtures" / "m2" / case / "source.json"
    golden = json.loads(fixture.read_text(encoding="utf-8"))
    root = tree(tmp_path, golden["files"])
    result = assemble_source(root)
    actual = result.to_dict()
    assert {key: actual[key] for key in golden["expected"]} == golden["expected"]
    assert actual == assemble_source(root).to_dict()
    assert "".join(result.text[s.output_start:s.output_end] for s in result.spans) == result.text
    for span in result.spans:
        assert result.text[span.output_start:span.output_end] == golden["files"][span.file][span.source_start:span.source_end]


@pytest.mark.parametrize("command", ["input", "include"])
def test_unique_case_insensitive_include(tmp_path, command):
    root = tree(tmp_path, {"main.tex": "\\documentclass{article}\n\\" + command + "{sec/1_intro}",
                           "Sec/1_Intro.tex": "Introduction"})
    result = assemble_source(root)
    assert result.status == "ready"
    assert result.text.endswith("Introduction")
    assert result.includes[0]["target"] == "Sec/1_Intro.tex"
    assert [(i.code, i.severity, i.line) for i in result.issues] == [
        ("include_case_mismatch", "info", 2)]


@pytest.mark.parametrize("exact", [False, True])
def test_case_fallback_considers_both_include_directories(tmp_path, exact):
    root = tree(tmp_path, {"main.tex": r"\documentclass{article}\input{sub/body}",
                           "sub/body.tex": r"\input{part}", "Part.tex": "ROOT",
                           "sub/part.tex" if exact else "sub/PART.tex": "LOCAL"})
    result = assemble_source(root)
    if exact:
        assert result.status == "ready"
        assert result.includes[-1]["target"] == "sub/part.tex"
        assert not any(i.code == "include_case_mismatch" for i in result.issues)
    else:
        assert result.status == "error"
        assert result.includes[-1]["target"] is None
        assert "Ambiguous case-insensitive" in result.issues[-1].message

def test_inline_listing_options_and_braced_input(tmp_path):
    source = r"\documentclass{x}\begin{document}\lstinline[columns=fixed]{\input{fake}}\end{document}"
    bundle = assemble_source(tree(tmp_path, {"main.tex": source}))
    assert bundle.status == "ready"
    assert bundle.includes == []


def _doc(title, body="Text."):
    return ("\\documentclass{article}\n\\title{" + title + "}\n\\begin{document}\n"
            + body + "\n\\end{document}\n")


def _codes(result):
    return [issue.code for issue in result.issues]


def test_title_hint_selects_the_root_whose_title_matches_metadata(tmp_path):
    root = tree(tmp_path, {
        "paper.tex": _doc(r"Robust \textbf{Graph} Learning\\ at Scale", "Main."),
        "notes.tex": _doc("Lab notes", "Other."),
    })
    assert "ambiguous_root" in _codes(assemble_source(root))
    result = assemble_source(root, title_hint="Robust graph learning at scale")
    # A rule-selected root is a warning, so the bundle is parsed as needs_review.
    assert result.root == "paper.tex" and result.status == "needs_review"
    assert "root_selected_by_title" in _codes(result)
    assert all(i.severity == "warning" for i in result.issues if i.code == "root_selected_by_title")


def test_title_hint_matching_two_roots_falls_back_to_auxiliary_names(tmp_path):
    root = tree(tmp_path, {
        "main.tex": _doc("Robust Graph Learning"),
        "supplementary.tex": _doc("Robust Graph Learning"),
    })
    result = assemble_source(root, title_hint="Robust Graph Learning")
    assert result.root == "main.tex"
    assert "root_selected_by_name" in _codes(result)


@pytest.mark.parametrize("auxiliary", [
    "supp.tex", "supp_arxiv.tex", "SupplementaryMaterial.tex", "SI.tex", "appendix.tex",
    "rebuttal.tex", "response_to_reviewers.tex", "cover_letter.tex",
])
def test_single_non_auxiliary_candidate_is_selected_by_name(tmp_path, auxiliary):
    root = tree(tmp_path, {"main.tex": _doc("A"), auxiliary: _doc("B")})
    result = assemble_source(root)
    assert result.root == "main.tex"
    assert "root_selected_by_name" in _codes(result)


@pytest.mark.parametrize("files", [
    ("Manuscript1.tex", "Manuscript2.tex"),
    ("main.tex", "sub/main.tex"),
    ("sample-sigconf.tex", "sample-acmsmall.tex"),
    ("PRL_Letter.tex", "supplement.tex", "notes.tex"),
])
def test_no_unique_evidence_stays_ambiguous(tmp_path, files):
    root = tree(tmp_path, {name: _doc("Same title") for name in files})
    result = assemble_source(root, title_hint="Unrelated metadata title")
    assert result.root is None
    assert "ambiguous_root" in _codes(result)


def test_explicit_root_file_overrides_rules(tmp_path):
    root = tree(tmp_path, {"main.tex": _doc("A"), "supp.tex": _doc("B")})
    result = assemble_source(root, root_file="supp.tex", title_hint="A")
    assert result.root == "supp.tex"
    assert not {"root_selected_by_title", "root_selected_by_name"} & set(_codes(result))


def test_commented_title_does_not_hide_the_effective_title(tmp_path):
    # Shape of 2410.08025 v1: an old title commented out right above the real one.
    main = ("\\documentclass{article}\n%\\title{An Older Working Title}\n"
            "\\title{Robust Graph Learning}\n\\begin{document}\nMain.\n\\end{document}\n")
    root = tree(tmp_path, {"main.tex": main, "notes.tex": _doc("Lab notes")})
    result = assemble_source(root, title_hint="Robust Graph Learning")
    assert result.root == "main.tex"
    assert "root_selected_by_title" in _codes(result)


def test_commented_empty_title_still_counts_the_real_title_as_a_match(tmp_path):
    # Shape of 2410.09510 v2: both templates carry the metadata title, one after a
    # commented-out \title{}. Two title matches means the title rule cannot decide.
    neurips = ("\\documentclass{article}\n% \\title{}\n\\usepackage{neurips_2025}\n"
               "\\title{Robust Graph Learning}\n\\begin{document}\nA.\n\\end{document}\n")
    root = tree(tmp_path, {
        "iclr_workshop/iclr2025_conference.tex": _doc("Robust Graph Learning"),
        "neurips/neurips_2025.tex": neurips,
    })
    result = assemble_source(root, title_hint="Robust Graph Learning")
    assert result.root is None
    assert "ambiguous_root" in _codes(result)


def test_title_in_disabled_branch_or_comment_environment_is_ignored(tmp_path):
    hidden = ("\\documentclass{article}\n\\iffalse\n\\title{Robust Graph Learning}\n\\fi\n"
              "\\begin{comment}\n\\title{Robust Graph Learning}\n\\end{comment}\n"
              "\\title{Something Else}\n\\begin{document}\nB.\n\\end{document}\n")
    main = ("\\documentclass{article}\n\\title{Robust Graph % line break kept\n"
            "Learning}\n\\begin{document}\nA.\n\\end{document}\n")
    root = tree(tmp_path, {"hidden.tex": hidden, "main.tex": main})
    result = assemble_source(root, title_hint="Robust Graph Learning")
    assert result.root == "main.tex"
    assert "root_selected_by_title" in _codes(result)


def test_title_inside_unevaluated_conditional_is_read(tmp_path):
    # JASA-style blind switch: \if1\blind{...}\fi cannot be evaluated by the scanner,
    # but the title inside it is the paper's title.
    main = ("\\documentclass{article}\n\\def\\blind{0}\n\\if1\\blind\n{\n"
            "\\title{\\bf Robust Graph Learning}\n}\\fi\n\\begin{document}\nA.\n\\end{document}\n")
    root = tree(tmp_path, {"main.tex": main, "notes.tex": _doc("Lab notes")})
    result = assemble_source(root, title_hint="Robust Graph Learning")
    assert result.root == "main.tex"
    assert "root_selected_by_title" in _codes(result)


def test_missing_input_is_a_warning_and_the_version_still_assembles(tmp_path):
    # epsf comes from the TeX distribution; figure.tikz is an asset M1 does not keep.
    result = assemble_source(tree(tmp_path, {
        "main.tex": "\\documentclass{article}\\input epsf\n\\begin{document}A\\input{figure.tikz}B\\end{document}",
    }))
    assert result.status == "needs_review"
    assert [i.code for i in result.issues] == ["missing_input", "missing_input"]
    assert all(i.severity == "warning" for i in result.issues)
    assert [entry["status"] for entry in result.includes] == ["missing", "missing"]
    assert "A" in result.text and "B" in result.text


def test_quoted_input_name_is_resolved(tmp_path):
    result = assemble_source(tree(tmp_path, {
        "main.tex": '\\documentclass{article}\\begin{document}\\input{"./sections/intro.tex"}\\end{document}',
        "sections/intro.tex": "INTRO",
    }))
    assert result.status == "ready" and "INTRO" in result.text


def test_missing_section_file_fails_the_version(tmp_path):
    # Parsing on would silently drop the Results section.
    result = assemble_source(tree(tmp_path, {
        "main.tex": "\\documentclass{article}\\begin{document}A\\include{sections/results}B\\end{document}",
    }))
    assert result.status == "error"
    assert [(i.code, i.severity) for i in result.issues] == [("missing_content", "error")]
    assert [entry["status"] for entry in result.includes] == ["missing"]


@pytest.mark.parametrize("main", [
    # A macro file read in the preamble holds no sentence.
    "\\documentclass{article}\\input{macros}\\begin{document}A\\end{document}",
    # TeX distribution file loaded in the body.
    "\\documentclass{article}\\begin{document}\\input xy\nA\\end{document}",
    # Picture and overlay assets that M1 does not keep.
    "\\documentclass{article}\\begin{document}\\input{fig/plot.pgf}\\input{a.pdf_tex}A\\end{document}",
])
def test_missing_resource_is_only_a_warning(tmp_path, main):
    result = assemble_source(tree(tmp_path, {"main.tex": main}))
    assert result.status == "needs_review"
    assert {i.code for i in result.issues} == {"missing_input"}


def test_missing_input_inside_an_included_body_file_is_content(tmp_path):
    # body.tex is read after \\begin{document}, so its own \\input is body text too.
    result = assemble_source(tree(tmp_path, {
        "main.tex": "\\documentclass{article}\\begin{document}\\input{body}\\end{document}",
        "body.tex": "Intro. \\input{sec/method}",
    }))
    assert "missing_content" in _codes(result) and result.status == "error"


def test_body_started_in_an_included_file_makes_later_inputs_content(tmp_path):
    # start.tex opens the document; the missing section is read back in main.tex.
    result = assemble_source(tree(tmp_path, {
        "main.tex": "\\documentclass{article}\\input{start}\\include{sections/results}\\end{document}",
        "start.tex": "\\begin{document}Intro.",
    }))
    assert "missing_content" in _codes(result) and result.status == "error"


@pytest.mark.parametrize("argument,code", [
    # physics is also a package name, but a path makes it the author's file.
    ("sections/physics", "missing_content"),
    ("./physics", "missing_content"),
    ("./physics.tex", "missing_content"),
    ('"./physics.tex"', "missing_content"),
    ("physics", "missing_input"),
])
def test_distribution_name_counts_only_as_a_bare_name(tmp_path, argument, code):
    result = assemble_source(tree(tmp_path, {
        "main.tex": "\\documentclass{article}\\begin{document}A\\include{" + argument + "}\\end{document}",
    }))
    assert [i.code for i in result.issues if i.code.startswith("missing_")] == [code]
