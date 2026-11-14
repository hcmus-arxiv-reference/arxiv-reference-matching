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
