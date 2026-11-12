"""Small synthetic folders for main-file selection and JSON export."""

import json

import pytest

from src.parse.MultifileGathering.file_tree import FileTree, build_file_tree
from src.parse.MultifileGathering import file_tree


@pytest.fixture(autouse=True)
def default_output(tmp_path, monkeypatch):
    output = tmp_path / "output" / "file_tree.json"
    monkeypatch.setattr(file_tree, "DEFAULT_OUTPUT", output)
    return output


def write_files(folder, files):
    for name, text in files.items():
        path = folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


def test_quoted_and_dotted_input_names_match_merged_dependencies(tmp_path):
    write_files(tmp_path, {
        "main.tex": r'\documentclass{article}\input{"./0.abstract"}\input{part.beta_0.5}',
        "0.abstract.tex": "ABSTRACT", "part.beta_0.5.tex": "BODY",
    })
    result = build_file_tree(tmp_path)
    assert result.main_file == "main.tex"
    assert result.input_files == ("0.abstract.tex", "part.beta_0.5.tex")


def test_single_file_and_repeat_run(tmp_path, default_output):
    write_files(tmp_path, {"only.tex": "A sentence."})
    expected = FileTree("only.tex", ())
    assert build_file_tree(tmp_path) == expected
    assert build_file_tree(tmp_path) == expected
    assert not (tmp_path / "file_tree.json").exists()
    assert json.loads(default_output.read_text()) == {
        "main_file": "only.tex", "input_files": [],
    }


@pytest.mark.parametrize("files,main", [
    ({"a.tex": r"\input{x}", "b.tex": r"\include{x}",
      "z.tex": r"\documentclass{article}"}, "z.tex"),
    ({"a.tex": r"\include{x}", "z.tex": r"\input{x}"}, "z.tex"),
    ({"a.tex": "Text", "z.tex": r"\include{x}"}, "z.tex"),
    ({"a.tex": r"\documentclass{article}",
      "z.tex": r"\documentclass{book}"}, "a.tex"),
])
def test_command_priority_and_ties(tmp_path, files, main):
    write_files(tmp_path, files)
    assert build_file_tree(tmp_path).main_file == main


@pytest.mark.parametrize("files,main", [
    ({"a.tex": r"\documentclass{standalone}",
      "z.tex": r"\documentclass{article}"}, "z.tex"),
    ({"a.tex": r"\documentclass[9pt]{beamer}",
      "z.tex": r"\documentclass{IEEEtran}"}, "z.tex"),
    ({"a.tex": "\\documentclass % class options\n[10pt] % class name\n{standalone}",
      "z.tex": r"\documentclass{article}"}, "z.tex"),
    ({"a.tex": r"\documentclass{standalone}",
      "nested/main.tex": r"\documentclass{article}"}, "nested/main.tex"),
    ({"a/nested.tex": r"\documentclass{article}",
      "z.tex": r"\documentclass{article}"}, "z.tex"),
    ({"a.tex": r"\documentclass{standalone}", "refs.bib": ""}, "a.tex"),
    ({"a.tex": r"\documentclass{beamer}", "refs.bib": ""}, "a.tex"),
    ({"a.tex": r"\input{part}",
      "nested/slides.tex": r"\documentclass{beamer}"}, "nested/slides.tex"),
    ({"a.tex": r"% \documentclass{article}" "\n" r"\documentclass{standalone}",
      "z.tex": r"\documentclass{article}"}, "z.tex"),
    ({"a.tex": r"\documentclass[broken", "z.tex": r"\documentclass{article}"}, "a.tex"),
])
def test_main_class_and_location_preferences(tmp_path, files, main):
    write_files(tmp_path, files)
    assert build_file_tree(tmp_path).main_file == main


@pytest.mark.parametrize("body", ["Plain text", r"\input{part}"])
def test_documentclass_has_priority_over_main_filename(tmp_path, body):
    write_files(tmp_path, {
        "main.tex": body,
        "article.tex": r"\documentclass{article}\input{part}\input{extra}",
        "part.tex": "Part", "extra.tex": "Extra",
    })
    result = build_file_tree(tmp_path)
    assert result == FileTree("article.tex", ("part.tex", "extra.tex"))


def test_main_filename_breaks_ties_between_documentclass_roots(tmp_path):
    write_files(tmp_path, {
        "main.tex": r"\documentclass{article}\input{intro}",
        "supplementary.tex": r"\documentclass{article}\input{intro}\input{extra}",
        "intro.tex": "Introduction", "extra.tex": "Extra",
    })
    assert build_file_tree(tmp_path) == FileTree("main.tex", ("intro.tex",))


def test_main_filename_is_preferred_without_documentclass(tmp_path):
    write_files(tmp_path, {"main.tex": "Main", "other.tex": r"\input{part}", "part.tex": "Part"})
    assert build_file_tree(tmp_path) == FileTree("main.tex", ())


@pytest.mark.parametrize("selection,expected", [
    ("intro", ("intro.tex", "note.tex")),
    ("", ("note.tex",)),
    (" intro.tex , method ", ("intro.tex", "method.tex", "note.tex")),
])
def test_includeonly_filters_include_but_not_input(tmp_path, selection, expected):
    write_files(tmp_path, {
        "main.tex": (r"\documentclass{article}" + "\\includeonly{" + selection + "}"
                     r"\begin{document}\include{intro}\include{method}\input{note}\end{document}"),
        "intro.tex": "Introduction", "method.tex": "Methods", "note.tex": "Note",
    })
    assert build_file_tree(tmp_path) == FileTree("main.tex", expected)


def test_includeonly_in_input_preamble_applies_before_following_includes(tmp_path):
    write_files(tmp_path, {
        "main.tex": (r"\documentclass{article}\includeonly{intro}\input{settings}"
                     r"\begin{document}\include{intro}\include{method}\end{document}"),
        "settings.tex": r"\includeonly{method}",
        "intro.tex": r"\input{excluded_child}",
        "excluded_child.tex": "Excluded child",
        "method.tex": r"\input{parts/detail}",
        "parts/detail.tex": "Detail",
    })
    assert build_file_tree(tmp_path) == FileTree(
        "main.tex", ("settings.tex", "method.tex", "parts/detail.tex")
    )


def test_commented_includeonly_is_ignored(tmp_path):
    write_files(tmp_path, {
        "main.tex": (r"\documentclass{article}" "\n" r"% \includeonly{}" "\n"
                     r"\include{intro}\include{method}"),
        "intro.tex": "Introduction", "method.tex": "Methods",
    })
    assert build_file_tree(tmp_path).input_files == ("intro.tex", "method.tex")


def test_includeonly_is_used_when_ranking_candidate_dependencies(tmp_path):
    write_files(tmp_path, {
        "a.tex": r"\documentclass{article}\includeonly{}\include{one}\include{two}",
        "z.tex": r"\documentclass{article}\input{one}",
        "one.tex": "One", "two.tex": "Two",
    })
    assert build_file_tree(tmp_path) == FileTree("z.tex", ("one.tex",))


def test_root_main_filename_preferred_over_nested_main(tmp_path):
    write_files(tmp_path, {
        "main.tex": r"\documentclass{article}",
        "a/main.tex": r"\documentclass{article}\input{part}",
        "a/part.tex": "Part",
    })
    assert build_file_tree(tmp_path) == FileTree("main.tex", ())


def test_article_beats_template_and_supplement_by_recursive_dependencies(tmp_path):
    write_files(tmp_path, {
        "iclr2025_conference.tex": r"\documentclass{article}\input{math_commands}",
        "paper.tex": r"\documentclass{article}\input{math_commands}\input{sections/intro}",
        "supp_main.tex": r"\documentclass{article}\input{math_commands}\input{extra}",
        "math_commands.tex": "Definitions",
        "sections/intro.tex": r"\input{method}",
        "sections/method.tex": "Methods",
        "extra.tex": "Supplement",
    })
    assert build_file_tree(tmp_path) == FileTree(
        "paper.tex", ("math_commands.tex", "sections/intro.tex", "sections/method.tex")
    )


def test_repeated_missing_and_commented_inputs_do_not_inflate_main_score(tmp_path):
    write_files(tmp_path, {
        "a.tex": (r"\documentclass{article}\input{one}\input{one}\input{one}\input{missing}"
                  "\n" r"% \input{two}\input{three}"),
        "z.tex": r"\documentclass{article}\input{two}\input{three}",
        "one.tex": "One", "two.tex": "Two", "three.tex": "Three",
    })
    assert build_file_tree(tmp_path).main_file == "z.tex"


def test_direct_sections_outrank_supplement_with_more_nested_figures(tmp_path):
    write_files(tmp_path, {
        "paper.tex": r"\documentclass{article}\input{intro}\input{method}\input{results}",
        "supp_main.tex": r"\documentclass{article}\input{appendix}",
        "intro.tex": "Introduction", "method.tex": "Methods", "results.tex": "Results",
        "appendix.tex": r"\input{fig1}\input{fig2}\input{fig3}\input{fig4}",
        "fig1.tex": "Figure 1", "fig2.tex": "Figure 2",
        "fig3.tex": "Figure 3", "fig4.tex": "Figure 4",
    })
    assert build_file_tree(tmp_path) == FileTree("paper.tex", ("intro.tex", "method.tex", "results.tex"))


def test_input_cycles_terminate_while_ranking_main(tmp_path):
    write_files(tmp_path, {
        "a.tex": r"\documentclass{article}",
        "z.tex": r"\documentclass{article}\input{part}",
        "part.tex": r"\input{z}\input{part}",
    })
    assert build_file_tree(tmp_path) == FileTree("z.tex", ("part.tex",))


def test_non_tex_dependencies_do_not_inflate_main_score(tmp_path):
    write_files(tmp_path, {
        "a.tex": r"\documentclass{article}\input{one.txt}\input{two.txt}",
        "z.tex": r"\documentclass{article}\input{part}",
        "one.txt": "One", "two.txt": "Two", "part.tex": "Part",
    })
    assert build_file_tree(tmp_path) == FileTree("z.tex", ("part.tex",))


def test_recursive_dependencies_comments_missing_files_and_cycles(tmp_path):
    write_files(tmp_path, {
        "main.tex": (r"\documentclass{article}" "\n"
                     r"% \input{unused}" "\n"
                     r"\input{parts/one}\include{two.tex}\input{missing}\input{two}"),
        "parts/one.tex": r"\input{nested}\input{../main}",
        "parts/nested.tex": "Nested text",
        "two.tex": "Second part",
        "unused.tex": "Unused text",
    })
    assert build_file_tree(tmp_path) == FileTree(
        "main.tex", ("parts/one.tex", "parts/nested.tex", "two.tex")
    )


@pytest.mark.parametrize("files", [{}, {"a.tex": "Text", "b.tex": "Text"}])
def test_no_main_still_writes_json(tmp_path, files, default_output):
    write_files(tmp_path, files)
    assert build_file_tree(tmp_path) == FileTree(None, ())
    assert json.loads(default_output.read_text())["main_file"] is None


def test_single_non_tex_file(tmp_path):
    write_files(tmp_path, {"paper.pdf": "PDF placeholder"})
    assert build_file_tree(tmp_path) == FileTree("paper.pdf", ())


def test_custom_output_and_outside_dependency(tmp_path):
    source = tmp_path / "source"
    write_files(source, {
        "main.tex": r"\documentclass{article}\input{../outside}",
        "unused.tex": "Unused",
    })
    write_files(tmp_path, {"outside.tex": "Outside"})
    output = tmp_path / "results" / "tree.json"
    assert build_file_tree(source, output) == FileTree("main.tex", ())
    assert output.is_file()


def test_invalid_folder(tmp_path):
    with pytest.raises(NotADirectoryError):
        build_file_tree(tmp_path / "missing")
