from scripts.m3_auto_match import candidate, match, evaluate

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
