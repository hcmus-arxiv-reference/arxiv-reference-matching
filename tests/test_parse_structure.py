"""Check hand-labelled Structure and BibSource examples against their source."""
import json
from pathlib import Path

import pytest


@pytest.mark.parametrize("case", [
    "multi-file-input", "comments-and-verbatim", "levels-skip", "appendix-ack-refs",
])
def test_structure_golden_spans(case):
    directory = Path(__file__).parent / "fixtures" / "m2" / case

    def read(name):
        return json.loads((directory / name).read_text(encoding="utf-8"))

    source = read("source.json")["expected"]["text"]
    tree = read("B.v1.json")
    bib = read("B'.v1.json")
    root = tree["root"]
    assert (tree["arxiv_id"], tree["version"]) == (bib["arxiv_id"], bib["version"])
    assert root["span"] == [source.index("\\begin{document}\n") + len("\\begin{document}\n"),
                            source.index("\\end{document}")]

    def check_children(parent):
        cursor, stop = parent["span"]
        for node in parent["children"]:
            start, end = node["span"]
            assert cursor <= start < end <= stop
            cursor = end
            original = source[start:end]
            if node["node"] == "Section":
                star = "*" if node["starred"] else ""
                assert original.startswith(f"\\{node['kind']}{star}{{{node['title_raw']}}}")
                check_children(node)
            else:
                if case == "comments-and-verbatim" and original.startswith("%"):
                    comment, newline, rest = original.partition("\n")
                    original = " " * len(comment) + newline + rest
                assert node["raw"] == original

    check_children(root)
    references = [source[a:b] for entry in tree["dropped"] if entry["reason"] == "references"
                  for a, b in [entry["span"]]]
    if case == "appendix-ack-refs":
        assert len(references) == 1
        assert references[0] == source[source.index(r"\section*{References}"):source.index(r"\appendix")]
        assert bib["bibitems_raw"] == [references[0].split("\n", 2)[2].split(r"\end{thebibliography}")[0]]
        assert bib["cite_keys_used"] == ["one"]
    else:
        assert not references and not bib["bibitems_raw"] and not bib["cite_keys_used"]

    from src.parse.source import SourceBundle
    from src.parse.structure import build_structure
    from src.parse.types import validate_B, validate_B_prime

    built, bibliography = build_structure(SourceBundle(status="ready", text=source),
                                         tree["arxiv_id"], tree["version"])
    assert built.to_dict() == tree
    assert bibliography.to_dict() == bib
    validate_B(built, source)
    validate_B_prime(bibliography)


def test_math_nested_environments_and_bibliography(tmp_path):
    from hashlib import sha256

    from src.parse.source import assemble_source
    from src.parse.structure import build_structure
    from src.parse.types import validate_B, validate_B_prime

    directory = tmp_path / "2508-02872" / "v1"
    directory.mkdir(parents=True)
    files = {"main.tex": r"""\documentclass{article}
\addbibresource{cited.bib}
\begin{document}
\section[short]{Long {title}}
\begin{figure}\begin{center}\citep[p. 2]{a,b}\end{center}\end{figure}
$$x$$ \[y\]
\bibliography{missing,cited}
\end{document}""", "cited.bib": "@misc{a}", "unused.bib": "@misc{x}"}
    hashes = {}
    for name, value in files.items():
        data = value.encode()
        (directory / name).write_bytes(data)
        hashes[name] = sha256(data).hexdigest()
    (directory / "source.json").write_text(json.dumps({
        "format": 1, "status": "success", "arxiv_id": "2508.02872",
        "version": 1, "checksum": "fixture", "files": hashes,
    }))
    source = assemble_source(directory, require_receipt=True)
    tree, bib = build_structure(source, "2508.02872", 1, directory)
    section, = tree.root.children
    assert section.title_raw == "Long {title}"
    assert [b.type for b in section.children] == ["env", "display_math", "display_math"]
    assert bib.cite_keys_used == ["a", "b"]
    assert bib.bib_files == {"cited.bib": "@misc{a}"}
    assert bib.missing_bib == ["missing.bib"]
    validate_B(tree, source.text)
    validate_B_prime(bib, {"cited.bib", "unused.bib"})

    from scripts.measure_structure import measure_sample

    raw = tmp_path / "raw"
    raw.mkdir()
    directory.parent.rename(raw / directory.parent.name)
    receipt = raw / "2508-02872" / "v1" / "source.json"
    entry = {"version": 1, "status": "success",
             "receipt_sha256": sha256(receipt.read_bytes()).hexdigest()}
    plan = {"data_origin": "mock", "publications": [
        {"arxiv_id": "2508.02872", "versions": [entry]}]}
    result = measure_sample(plan, tmp_path)
    assert result["ready_tex_versions"] == result["tex_versions"] == 1
    assert result["headings_by_kind"] == {"section": 1}
    assert result["structure_failures"] == []
    assert result["all_tex_versions_checked_without_references"]

    # A second TeX Version has a valid receipt but no document root.
    broken = receipt.parent.parent / "v2"
    broken.mkdir()
    content = b"No document class here."
    (broken / "part.tex").write_bytes(content)
    record = json.loads(receipt.read_bytes())
    record.update(version=2, files={"part.tex": sha256(content).hexdigest()})
    (broken / "source.json").write_text(json.dumps(record))
    plan["publications"][0]["versions"].append({
        "version": 2, "status": "success",
        "receipt_sha256": sha256((broken / "source.json").read_bytes()).hexdigest(),
    })
    partial = measure_sample(plan, tmp_path)
    assert partial["publications_with_references_heading"] == []
    assert not partial["all_tex_versions_checked_without_references"]


@pytest.mark.parametrize("title", [r"\refname", r"\bibname"])
def test_bibliography_title_macro_stops_at_next_peer_heading(title):
    from src.parse.source import SourceBundle
    from src.parse.structure import build_structure
    from src.parse.types import validate_B

    text = (r"\begin{document}\section{Results}Body.\section*{" + title
            + r"}Citations.\section{Appendix}Extra.\end{document}")
    tree, _ = build_structure(SourceBundle(status="ready", text=text), "2508.02872", 1)
    validate_B(tree, text)
    assert [node.title_raw for node in tree.root.children] == ["Results", "Appendix"]
    assert any(drop["reason"] == "references" for drop in tree.dropped)

def test_heading_wrappers_and_formatting_command():
    from scripts.compare_structure import custom_tokens, headings
    from src.parse.source import SourceBundle
    from src.parse.structure import build_structure
    from src.parse.types import validate_B

    text = r"""\begin{document}
\titlespacing*{\section}{0pt}{0pt}{0pt}
\begin{CJK}{UTF8}{gbsn}\section{Body}\end{CJK}
\begin{appendix}\section{Extra}\end{appendix}
\end{document}"""
    tree, _ = build_structure(SourceBundle(status="ready", text=text), "2508.02872", 1)
    validate_B(tree, text)
    assert [n.title_raw for n in headings(tree.root)] == ["Body", "Extra"]
    assert len(custom_tokens(text)) == 3


def test_nested_bibliography_is_extracted_before_wrapper_becomes_a_block():
    from src.parse.source import SourceBundle
    from src.parse.structure import build_structure
    from src.parse.types import validate_B, validate_B_prime

    text = (r"\begin{document}\section{Methods}\begin{small}Before \cite{a}."
            r"\begin{center}\begin{thebibliography}{9}\bibitem{a}Entry."
            r"\end{thebibliography}\end{center}After.\end{small}\end{document}")
    tree, bib = build_structure(SourceBundle(status="ready", text=text), "2508.02872", 1)
    validate_B(tree, text)
    validate_B_prime(bib)
    blocks = "".join(block.raw for block in tree.root.children[0].children)
    assert "Before" in blocks and "After" in blocks and "Entry." not in blocks
    assert bib.bibitems_raw == [r"\bibitem{a}Entry."]
    assert bib.cite_keys_used == ["a"]


def _structure(tmp_path, body):
    from src.parse.source import assemble_source
    from src.parse.structure import build_structure
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\n" + body + "\n\\end{document}\n",
        encoding="utf-8", newline="\n")  # LF on Windows too: the test compares offsets
    bundle = assemble_source(tmp_path)
    tree, bib = build_structure(bundle, "2508.00001", 1)

    def raws(node):
        for child in node.children:
            yield from ([child.raw] if hasattr(child, "raw") else raws(child))
    return bundle, "".join(raws(tree.root)), bib


def test_iffalse_branch_is_blanked_with_its_citations(tmp_path):
    body = "Kept \\cite{a}.\n\\iffalse\nDropped draft \\cite{b}.\n\\fi\nAfter."
    bundle, text, bib = _structure(tmp_path, body)
    assert "Kept" in text and "After." in text
    assert "Dropped" not in text and "\\iffalse" not in text and "\\fi" not in text
    assert bib.cite_keys_used == ["a"]
    # Blanking keeps offsets and newlines: only the off span becomes spaces.
    off = body[body.index("\\iffalse"):body.index("\\fi") + len("\\fi")]
    assert text == body.replace(off, "".join(c if c == "\n" else " " for c in off)) + "\n"


def test_iftrue_else_keeps_the_true_branch_and_nested_conditionals(tmp_path):
    body = ("\\iftrue\nShown \\cite{a}.\n\\else\nHidden \\cite{b}.\n\\fi\n"
            "\\iffalse\nOuter \\iftrue inner \\fi tail \\cite{c}.\n\\fi\nEnd.")
    _, text, bib = _structure(tmp_path, body)
    assert "Shown" in text and "End." in text
    assert not any(word in text for word in ("Hidden", "Outer", "inner", "tail"))
    assert bib.cite_keys_used == ["a"]


def test_unevaluated_conditional_keeps_text(tmp_path):
    # Neither branch of \if1\blind can be decided without TeX; keep the text as before.
    body = "\\if1\\blind\nAuthor version.\n\\fi\nEnd."
    _, text, _ = _structure(tmp_path, body)
    assert "Author version." in text


def _sentences(tmp_path, body):
    """Normalized sentences of a one-file Version, as they reach ``elements``."""
    from src.parse.leaves import build_leaves
    from src.parse.normalize import normalize
    from src.parse.source import assemble_source
    from src.parse.structure import build_structure
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\n" + body + "\n\\end{document}\n",
        encoding="utf-8", newline="\n")
    tree, _ = build_structure(assemble_source(tmp_path), "2508.00001", 1)

    def walk(node):
        for child in node.children:
            if hasattr(child, "kind") and hasattr(child, "raw"):
                if child.kind == "sentence":
                    yield normalize("sentence", child.raw)
            else:
                yield from walk(child)
    return list(walk(build_leaves(tree).root))


@pytest.mark.parametrize("body", [
    "\\ifnum 1<2 Visible.\\else Secret.\\fi",
    "\\iffalse Secret.\\else Visible.\\fi",
    "\\iftrue Visible.\\else Secret.\\fi",
    "\\iftrue Visible.\\fi",
    "Visible.",
])
def test_decided_conditional_leaves_only_the_text_of_its_branch(tmp_path, body):
    # Every spelling must give the same Element, so Versions deduplicate.
    assert _sentences(tmp_path, body) == ["Visible."]
