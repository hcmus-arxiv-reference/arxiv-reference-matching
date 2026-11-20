import json
from dataclasses import asdict
from pathlib import Path

from src.parse.types import (
    Block,
    Section,
    StructureTree,
    validate_B,
    validate_C,
)
from src.parse.leaves import build_leaves

FIXTURE = (
    Path(__file__).parent
    / "fixtures/m2/lists-figures-math"
)


def decode_section(data):
    children = []

    for child in data["children"]:
        if "type" in child:
            children.append(
                Block(
                    type=child["type"],
                    env=child["env"],
                    raw=child["raw"],
                    span=tuple(child["span"]),
                )
            )
        else:
            children.append(decode_section(child))

    return Section(
        kind=data["kind"],
        title_raw=data["title_raw"],
        starred=data["starred"],
        span=tuple(data["span"]),
        children=children,
    )


def load_structure_tree():
    data = json.loads(
        (FIXTURE / "B.v1.json").read_text(encoding="utf-8")
    )

    return StructureTree(
        arxiv_id=data["arxiv_id"],
        version=data["version"],
        root=decode_section(data["root"]),
        dropped=data["dropped"],
        issues=data["issues"],
        structure_version=data["structure_version"],
    )


def test_golden_B_validates():
    tree = load_structure_tree()
    assert validate_B(tree, raise_on_error=False) == []


def test_golden_C_matches_build_leaves():
    tree = load_structure_tree()
    actual = build_leaves(tree)

    expected = json.loads(
        (FIXTURE / "C.v1.json").read_text(encoding="utf-8")
    )

    actual_data = json.loads(
        json.dumps(asdict(actual), ensure_ascii=False)
    )

    assert actual_data == expected


def test_golden_C_validates_against_B():
    tree = load_structure_tree()
    result = build_leaves(tree)

    assert validate_C(result, tree) == []


def test_leaves_golden_from_tex():
    from src.parse.source import SourceBundle
    from src.parse.structure import build_structure

    tex = (FIXTURE / "v1/main.tex").read_text(encoding="utf-8")
    expected_b = load_structure_tree()
    source = SourceBundle(status="ready", text=tex)
    tree, _ = build_structure(source, expected_b.arxiv_id, expected_b.version)
    assert asdict(tree) == asdict(expected_b)

    leaves = build_leaves(tree)
    assert validate_C(leaves, tree) == []
    expected_c = json.loads((FIXTURE / "C.v1.json").read_text(encoding="utf-8"))
    assert json.loads(json.dumps(asdict(leaves))) == expected_c
