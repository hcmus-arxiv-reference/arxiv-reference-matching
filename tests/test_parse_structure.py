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
