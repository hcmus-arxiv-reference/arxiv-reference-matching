"""Kiểm tra entry point mà không gọi mạng thật."""

from unittest.mock import patch

from scripts import check_hf
from src.common.config import get_settings


def test_missing_credentials_do_not_call_network(capsys):
    with patch.object(check_hf, "get_settings", return_value=get_settings(env={})), \
            patch.object(check_hf, "ensure_repo") as ensure:
        assert check_hf.main() == 2
    ensure.assert_not_called()
    assert "HF_TOKEN" in capsys.readouterr().out


def test_configured_check_invokes_ensure_once(capsys):
    settings = get_settings(env={"MEMBER_NAME": "bao", "HF_TOKEN": "synthetic-secret", "HF_REPO_ID": "test/repo"})
    with patch.object(check_hf, "get_settings", return_value=settings), \
            patch.object(check_hf, "ensure_repo") as ensure:
        assert check_hf.main() == 0
    ensure.assert_called_once_with(settings)
    output = capsys.readouterr().out
    assert "private" in output
    assert "synthetic-secret" not in output


def test_network_failure_does_not_print_raw_error(capsys):
    settings = get_settings(env={"MEMBER_NAME": "bao", "HF_TOKEN": "synthetic-secret", "HF_REPO_ID": "test/repo"})
    with patch.object(check_hf, "get_settings", return_value=settings), \
            patch.object(check_hf, "ensure_repo", side_effect=RuntimeError("synthetic-secret")):
        assert check_hf.main() == 1
    assert "synthetic-secret" not in capsys.readouterr().out
