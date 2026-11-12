"""Unit tests for Milestone 2 shared types and boundary validators (A, B, B', C, D)."""
from __future__ import annotations

import pytest

from src.parse.source import Issue, SourceBundle, Span
from src.parse.types import (
    BibResult,
    BibSource,
    Block,
    Leaf,
    LeafTree,
    ListNode,
    Section,
    StructureTree,
    source_bundle_from_dict,
    validate_A,
    validate_B,
    validate_B_prime,
    validate_C,
    validate_D,
)


def test_validate_A_valid_and_round_trip():
    bundle = SourceBundle(
        status="ready",
        root="main.tex",
        text=r"\documentclass{article}\begin{document}Hi\end{document}",
        files=["main.tex"],
        unused_tex_files=["unused.tex"],
        spans=[Span(0, 55, "main.tex", 0, 55, 1)],
        issues=[],
        includes=[],
        checksums={"main.tex": "a" * 64},
    )
    assert validate_A(bundle) == []
    reloaded = source_bundle_from_dict(bundle.to_dict())
    assert reloaded == bundle
    assert validate_A(reloaded) == []

    empty_bundle = SourceBundle(status="empty_non_tex", root=None, text="")
    assert validate_A(empty_bundle) == []


def test_validate_A_rejects_broken_invariants():
    # empty_non_tex with non-empty text
    bad_empty = SourceBundle(status="empty_non_tex", root=None, text="non-empty")
    with pytest.raises(ValueError, match="empty_non_tex"):
        validate_A(bad_empty)

    # error status without error Issue
    bad_err = SourceBundle(
        status="error",
        issues=[Issue("warn_only", "warning", "main.tex", 1, "msg")],
    )
    with pytest.raises(ValueError, match="severity='error'"):
        validate_A(bad_err)

    # Discontinuous spans
    bad_span = SourceBundle(
        status="ready",
        root="main.tex",
        text="ABCDEF",
        files=["main.tex"],
        spans=[Span(0, 2, "main.tex", 0, 2, 1), Span(3, 6, "main.tex", 3, 6, 1)],
        checksums={"main.tex": "a" * 64},
    )
    errors = validate_A(bad_span, raise_on_error=False)
    assert any("không liên tục" in e for e in errors)


def test_validate_B_valid_and_relative_depth():
    # Document with subsection directly under document (levels-skip allowed)
    block = Block(type="text", env=None, raw="Hello world.", span=(20, 32))
    sub = Section(
        kind="subsection",
        title_raw="Background",
        starred=False,
        span=(5, 32),
        children=[block],
    )
    root = Section(
        kind="document",
        title_raw="",
        starred=False,
        span=(0, 40),
        children=[sub],
    )
    tree = StructureTree(
        arxiv_id="2508.02872",
        version=1,
        root=root,
        dropped=[{"reason": "preamble", "span": [0, 5]}, {"reason": "references", "span": [32, 40]}],
    )
    assert validate_B(tree) == []
    reloaded = StructureTree.from_dict(tree.to_dict())
    assert reloaded == tree
    assert validate_B(reloaded) == []


def test_validate_B_rejects_references_comments_and_inverted_depth():
    # 1) References section leaked into tree
    ref_sec = Section(
        kind="section",
        title_raw=r"\textbf{References}",
        starred=True,
        span=(10, 30),
        children=[],
    )
    tree_ref = StructureTree(
        arxiv_id="2508.02872",
        version=1,
        root=Section("document", "", False, (0, 40), [ref_sec]),
    )
    with pytest.raises(ValueError, match="References/Bibliography"):
        validate_B(tree_ref)

    # 2) Child section shallower than parent (section inside subsection)
    bad_child = Section("section", "Child", False, (10, 20), [])
    parent_sub = Section("subsection", "Parent", False, (5, 25), [bad_child])
    tree_depth = StructureTree(
        arxiv_id="2508.02872",
        version=1,
        root=Section("document", "", False, (0, 30), [parent_sub]),
    )
    with pytest.raises(ValueError, match="Cấp mục con"):
        validate_B(tree_depth)

    # 3) Unescaped comment in Block.raw
    comment_block = Block("text", None, "Hello % comment\n", (5, 21))
    tree_comment = StructureTree(
        arxiv_id="2508.02872",
        version=1,
        root=Section("document", "", False, (0, 30), [comment_block]),
    )
    with pytest.raises(ValueError, match="comment"):
        validate_B(tree_comment)


def test_validate_B_prime_valid_and_invalid():
    bib = BibSource(
        arxiv_id="2508.02872",
        version=1,
        bib_files={"refs.bib": "@article{k, title={T}}"},
        missing_bib=[],
        bibitems_raw=[r"\bibitem{smith20} J. Smith. Title. 2020."],
        cite_keys_used=["smith20", "k"],
    )
    assert validate_B_prime(bib, allowed_bib_files={"refs.bib"}) == []
    assert BibSource.from_dict(bib.to_dict()) == bib

    # Unsplit multiple keys in \cite{a,b}
    bad_bib = BibSource(
        arxiv_id="2508.02872",
        version=1,
        cite_keys_used=["a,b"],
    )
    with pytest.raises(ValueError, match="cite_keys_used"):
        validate_B_prime(bad_bib)


def test_validate_C_valid_and_no_lost_text():
    s1 = Leaf(kind="sentence", raw="We follow Smith et al.", span=(10, 32))
    s2 = Leaf(kind="sentence", raw="The loss is $L=1$.", span=(33, 51))
    item_leaf = Leaf(kind="sentence", raw="First point.", span=(60, 72))
    item_node = ListNode(kind="item", span=(55, 72), children=[item_leaf])
    list_node = ListNode(kind="itemize", span=(52, 75), children=[item_node])

    sec = Section(
        kind="section",
        title_raw="Intro",
        starred=False,
        span=(0, 80),
        children=[s1, s2, list_node],
    )
    leaf_tree = LeafTree(
        arxiv_id="2508.02872",
        version=1,
        root=Section("document", "", False, (0, 80), [sec]),
    )
    struct_tree = StructureTree(
        arxiv_id="2508.02872",
        version=1,
        root=Section(
            "document",
            "",
            False,
            (0, 80),
            [
                Section(
                    "section",
                    "Intro",
                    False,
                    (0, 80),
                    [
                        Block("text", None, "We follow Smith et al. The loss is $L=1$.", (10, 51)),
                        Block("env", "itemize", r"\begin{itemize}\item First point.\end{itemize}", (52, 98)),
                    ],
                )
            ],
        ),
    )
    assert validate_C(leaf_tree, structure_tree=struct_tree) == []
    reloaded = LeafTree.from_dict(leaf_tree.to_dict())
    assert reloaded == leaf_tree
    assert validate_C(reloaded) == []


def test_validate_C_rejects_remaining_block_and_invalid_list_hierarchy():
    # Block left inside LeafTree
    leftover = LeafTree(
        arxiv_id="2508.02872",
        version=1,
        root=Section(
            "document",
            "",
            False,
            (0, 20),
            [Block("text", None, "Text", (0, 4))],
        ),
    )
    with pytest.raises(ValueError, match="Block"):
        validate_C(leftover)

    # item directly under section (not inside itemize)
    orphan_item = LeafTree(
        arxiv_id="2508.02872",
        version=1,
        root=Section(
            "document",
            "",
            False,
            (0, 20),
            [ListNode("item", (0, 10), [Leaf("sentence", "Hello.", (0, 6))])],
        ),
    )
    with pytest.raises(ValueError, match="itemize"):
        validate_C(orphan_item)


def test_validate_D_valid_and_invalid():
    b1 = BibSource(arxiv_id="2508.02872", version=1, cite_keys_used=["smith20"])
    b2 = BibSource(arxiv_id="2508.02872", version=2, cite_keys_used=["Smith2020"])
    res = BibResult(
        arxiv_id="2508.02872",
        entries=[
            {
                "citation_key": "Smith2020",
                "entry_type": "article",
                "title": "Title",
                "authors": ["J. Smith"],
                "year": 2020,
                "doi": None,
                "journal": None,
                "url": None,
            },
            {
                "citation_key": "NoYearKey",
                "entry_type": "misc",
                "title": "Preprint",
                "authors": [],
                "year": None,
            },
        ],
        key_map={
            "1": {"smith20": "Smith2020"},
            "2": {"Smith2020": "Smith2020"},
        },
        raw_years={"NoYearKey": "forthcoming"},
        stats={"entry_before": 2, "entry_after": 1},
    )
    assert validate_D(res, bib_sources=[b1, b2]) == []
    assert BibResult.from_dict(res.to_dict()) == res

    # Key in key_map pointing to nonexistent entry
    bad_map = BibResult(
        arxiv_id="2508.02872",
        entries=res.entries,
        key_map={"1": {"smith20": "MissingKey"}},
    )
    with pytest.raises(ValueError, match="MissingKey"):
        validate_D(bad_map)

    # Missing cite_key from BibSource
    missing_cite = BibResult(
        arxiv_id="2508.02872",
        entries=res.entries,
        key_map={"1": {}, "2": {"Smith2020": "Smith2020"}},
    )
    with pytest.raises(ValueError, match="smith20"):
        validate_D(missing_cite, bib_sources=[b1, b2])
