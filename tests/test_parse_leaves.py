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




@pytest.mark.parametrize("env", ["proof", "abstract", "theorem", "quote"])
def test_prose_environment_preserves_offsets_and_splits(env):
    raw = rf"\begin{{{env}}}First sentence. Second sentence \cite{{a}}.\end{{{env}}}"
    tree = make_tree(raw, "env", env)
    result = build_leaves(tree)
    leaves = result.root.children[0].children
    assert [leaf.raw for leaf in leaves] == ["First sentence.", r"Second sentence \cite{a}."]
    for leaf in leaves:
        start, end = leaf.span
        assert raw[start:end] == leaf.raw
    assert validate_C(result, tree) == []
    leaves.pop()
    assert validate_C(result, tree, raise_on_error=False)


@pytest.mark.parametrize("env", ["eqnarray", "eqnarray*", "alignat", "alignat*"])
def test_formula_inside_subequations(env):
    equation = rf"\begin{{{env}}}x=1\end{{{env}}}"
    wrapped = r"\begin{subequations}" + equation + r"\end{subequations}"
    for raw, outer in [(equation, env), (wrapped, "subequations")]:
        tree = make_tree(raw, "env", outer)
        result = build_leaves(tree)
        leaf, = result.root.children[0].children
        assert (leaf.kind, leaf.raw) == ("formula", equation)
        assert validate_C(result, tree) == []


def test_description_label_with_braced_closing_bracket():
    raw = r"\begin{description}\item[Value {a]b}] First. Second.\end{description}"
    tree = make_tree(raw, "env", "description")
    node, = build_leaves(tree).root.children[0].children
    assert [leaf.raw for leaf in node.children[0].children] == [
        "[Value {a]b}]", "First.", "Second."
    ]


@pytest.mark.parametrize("env,setup", [
    ("enumerate", "[(K1)]"),
    ("enumerate", "[leftmargin=0.4cm]"),
    ("enumerate", "[(a)]"),
    ("enumerate", r"[label=(\roman*)]"),
    ("itemize", r"\vspace{-5pt}"),
])
def test_list_setup_in_theorem(env, setup):
    raw = (r"\begin{theorem}First. " + rf"\begin{{{env}}}{setup}"
           + r"\item[Precision] Actual content."
           + rf"\end{{{env}}}\end{{theorem}}")
    tree = make_tree(raw, "env", "theorem")
    result = build_leaves(tree)
    assert validate_C(result, tree) == []

    item = result.root.children[0].children[1].children[0]
    assert [leaf.raw for leaf in item.children] == ["[Precision]", "Actual content."]
    item.children.pop(0)
    assert validate_C(result, tree, raise_on_error=False)
