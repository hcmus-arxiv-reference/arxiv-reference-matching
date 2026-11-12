import json
from pathlib import Path
import pytest

from src.parse.leaves import build_leaves
from src.parse.types import (
    Block,
    Leaf,
    ListNode,
    Section,
    StructureTree,
    validate_C,
)


def make_tree(raw, block_type="text", env=None):
    block = Block(
        type=block_type,
        env=env,
        raw=raw,
        span=(0, len(raw)),
    )

    section = Section(
        kind="section",
        title_raw="Intro",
        starred=False,
        span=(0, len(raw)),
        children=[block],
    )

    root = Section(
        kind="document",
        title_raw="",
        starred=False,
        span=(0, len(raw)),
        children=[section],
    )

    return StructureTree(
        arxiv_id="2501.00001",
        version=1,
        root=root,
        dropped=[],
        issues=[],
        structure_version="1",
    )


def test_build_leaves_splits_text_and_preserves_spans():
    raw = "First sentence. Second sentence."
    tree = make_tree(raw)

    result = build_leaves(tree)
    leaves = result.root.children[0].children

    assert [leaf.raw for leaf in leaves] == [
        "First sentence.",
        "Second sentence.",
    ]

    assert leaves[0].span == (0, 15)
    assert leaves[1].span == (16, len(raw))

    assert validate_C(result, tree) == []


def test_inline_math_remains_inside_sentence():
    raw = r"Use $x=3.14$ here. Next sentence."
    result = build_leaves(make_tree(raw))

    leaves = result.root.children[0].children

    assert len(leaves) == 2
    assert all(isinstance(x, Leaf) for x in leaves)
    assert "$x=3.14$" in leaves[0].raw


def test_table_and_display_math_become_correct_leaf_kinds():
    raw = (
        r"Before. "
        r"\begin{table}A & B\end{table}"
        r"$$x=1$$"
        r"After."
    )

    result = build_leaves(make_tree(raw))
    leaves = result.root.children[0].children

    assert [x.kind for x in leaves] == [
        "sentence",
        "figure",
        "formula",
        "sentence",
    ]

    assert validate_C(result) == []


def test_nested_itemize_preserves_two_levels():
    raw = (
        r"\begin{itemize}"
        r"\item First outer sentence."
        r"\begin{itemize}"
        r"\item First inner sentence."
        r"\item Second inner sentence."
        r"\end{itemize}"
        r"\item Second outer sentence."
        r"\end{itemize}"
    )

    result = build_leaves(
        make_tree(raw, "env", "itemize")
    )

    outer = result.root.children[0].children[0]

    assert isinstance(outer, ListNode)
    assert outer.kind == "itemize"
    assert len(outer.children) == 2

    first_item = outer.children[0]

    assert first_item.kind == "item"
    assert any(
        isinstance(x, ListNode) and x.kind == "itemize"
        for x in first_item.children
    )

    assert validate_C(result) == []


@pytest.mark.parametrize(
    "env,raw",
    [
        (
            "enumerate",
            r"\begin{enumerate}\item First.\item Second.\end{enumerate}",
        ),
        (
            "description",
            r"\begin{description}\item[Input] First.\item[Output] Second.\end{description}",
        ),
    ],
)
def test_enumerate_and_description_map_to_itemize(env, raw):
    result = build_leaves(make_tree(raw, "env", env))

    node = result.root.children[0].children[0]

    assert isinstance(node, ListNode)
    assert node.kind == "itemize"
    assert len(node.children) == 2

    assert validate_C(result) == []


