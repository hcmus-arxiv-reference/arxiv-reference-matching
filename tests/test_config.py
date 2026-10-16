import pytest

from src.common.config import ArxivRange, get_settings


def test_range_ids_and_len():
    r = ArxivRange("2508", 2872, 2874)
    assert list(r.ids()) == ["2508.02872", "2508.02873", "2508.02874"]
    assert len(r) == 3


def test_range_contains():
    r = ArxivRange("2508", 2872, 7871)
    assert "2508.02872" in r
    assert "2508.07871" in r
    assert "2508.07872" not in r
    assert "2508.02871" not in r
    assert "2509.03000" not in r
    assert "2508.02872v2" not in r


@pytest.mark.parametrize("args", [("25-08", 1, 2), ("2508", 5, 1), ("2508", 0, 3), ("2508", 1, 100000)])
def test_range_invalid(args):
    with pytest.raises(ValueError):
        ArxivRange(*args)


def test_default_range_is_group_leader_range():
    s = get_settings(env={})
    assert len(s.arxiv_range) == 5000
    assert next(s.arxiv_range.ids()) == "2508.02872"


def test_env_overrides_and_blank_values():
    s = get_settings(
        env={
            "ARXIV_RANGE_PREFIX": "2509",
            "ARXIV_RANGE_START": "10",
            "ARXIV_RANGE_END": "12",
            "HF_TOKEN": "   ",
            "MEMBER_NAME": "nghiem",
        }
    )
    assert list(s.arxiv_range.ids()) == ["2509.00010", "2509.00011", "2509.00012"]
    assert s.hf_token is None
    assert s.member == "nghiem"


def test_user_agent_requires_email():
    with pytest.raises(ValueError):
        get_settings(env={}).user_agent()
    ua = get_settings(env={"CONTACT_EMAIL": "a@b.vn"}).user_agent()
    assert "mailto:a@b.vn" in ua


def test_s2_headers_only_include_key_when_set():
    base = {"CONTACT_EMAIL": "a@b.vn"}
    assert "x-api-key" not in get_settings(env=base).s2_headers()
    assert get_settings(env={**base, "S2_API_KEY": "k"}).s2_headers()["x-api-key"] == "k"


def test_require_hf_lists_missing():
    with pytest.raises(ValueError, match="HF_TOKEN"):
        get_settings(env={}).require_hf()


def test_settings_repr_does_not_expose_credentials():
    settings = get_settings(env={"HF_TOKEN": "synthetic-hf-secret", "S2_API_KEY": "synthetic-s2-secret"})
    assert "synthetic-hf-secret" not in repr(settings)
    assert "synthetic-s2-secret" not in repr(settings)
