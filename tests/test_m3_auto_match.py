import pytest

from scripts.m3_auto_match import align_gold, candidate, match, evaluate

RID = "1706.03762"


def ref(title):
    return candidate({"ref_title": title, "ref_authors": ["Lan Nguyen"]})


def test_explicit_id_and_version():
    assert match({"url": "https://arxiv.org/pdf/1706.03762v3.pdf"},
                 {RID: ref("Attention Is All You Need")})[0] == RID


def test_absent_id_beats_misleading_title():
    entry = {"journal": "arXiv:2310.01779", "title": "Large Language Models"}
    assert match(entry, {RID: ref("Large Language Models")})[2] == "id_outside_candidates"


def test_generic_substring_abstains():
    entry = {"title": "Chain-of-Thought Prompting Elicits Reasoning in Large Language Models"}
    assert match(entry, {RID: ref("Large Language Models")})[0] == ""


def test_latex_and_ties():
    entry = {"title": r'Discrete {S}chr\"{o}dinger operators on lattices'}
    c = ref("Discrete Schrödinger operators on lattices")
    assert match(entry, {RID: c})[0] == RID
    assert match(entry, {RID: c, "1901.01234": c})[2] == "ambiguous"


def test_metrics_wrong_id_counts_both_ways(tmp_path):
    k = ("2409.10001", "example")
    refs = {k[0]: {RID: ref("Attention Is All You Need"),
                   "1901.01234": ref("Another Real Candidate")}}
    result = evaluate({k: "1901.01234"}, {k: {"url": "arXiv:1706.03762"}}, refs, tmp_path)
    assert (result["tp"], result["fp"], result["fn"]) == (0, 1, 1)


def test_align_gold_resolves_aliases_once_per_affected_paper():
    gold = {("a", "old"): RID, ("a", "new"): RID, ("a", "other-old"): "",
            ("b", "old"): ""}
    expected = {("a", "new"): RID, ("a", "other"): "", ("b", "old"): ""}
    calls = []

    def get_map(pid):
        calls.append(pid)
        return {"old": "new", "other-old": "other"}

    assert align_gold(gold, dict.fromkeys(expected), get_map) == expected
    assert calls == ["a"]


def test_align_gold_rejects_conflicting_aliases():
    gold = {("a", "old"): "", ("a", "new"): RID}
    with pytest.raises(ValueError, match="mâu thuẫn"):
        align_gold(gold, {("a", "new"): {}}, lambda pid: {"old": "new"})


def test_align_gold_rejects_missing_target():
    with pytest.raises(ValueError, match="Thiếu khóa bibtex"):
        align_gold({("a", "old"): RID}, {}, lambda pid: {"old": "missing"})


def test_publication_split_reproducible_and_frozen():
    from collections import Counter
    from scripts.m3_auto_match import publication_splits

    members = list("abcde")
    owners = {f"{m}{i}": m for m in members for i in range(5)}
    manual = set(owners)
    available = [f"auto{i}" for i in range(40)]
    rows = publication_splits(manual, available, owners, members, 12)
    assert rows == publication_splits(manual, reversed(available), owners, reversed(members), 12)
    counts = Counter((r["pool"], r["partition"]) for r in rows)
    assert counts == {("manual", "test"): 5, ("manual", "valid"): 5, ("manual", "train"): 15,
                      ("auto", "test"): 5, ("auto", "valid"): 5, ("auto", "train"): 2}
    for member in members:
        parts = [r["partition"] for r in rows if owners.get(r["arxiv_id"]) == member]
        assert sorted(parts) == ["test", "train", "train", "train", "valid"]
    assert len({r["arxiv_id"] for r in rows}) == len(rows)
    assert rows == publication_splits(manual, available, owners, members, 12, rows)
    with pytest.raises(ValueError):
        publication_splits(manual, available, owners, members, 12, rows + rows[:1])


@pytest.mark.parametrize("archive,expected", [("arXiv", "explicit_id"), ("", "explicit_id"),
                                              ("HAL", "missing_title")])
def test_pilot_eprint_uses_archive_prefix(archive, expected):
    from scripts.m3_auto_match import pilot_entry

    raw = '@article{paper, eprint="1706.03762v2", archivePrefix={' + archive + '}}'
    assert match(pilot_entry(raw), {RID: ref("Attention Is All You Need")})[2] == expected


def test_pilot_conflicting_eprint_and_url_abstains():
    from scripts.m3_auto_match import pilot_entry

    raw = '@misc{x, eprint={1706.03762}, url={https://arxiv.org/abs/1901.01234}}'
    assert match(pilot_entry(raw), {RID: ref("Attention Is All You Need")})[:3] == (
        "", "unsure", "conflicting_ids")
