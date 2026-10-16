import pytest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from src.common.config import get_settings
from src.common import hf_io
from src.common.schema import empty_table, write_table
from src.common.hf_io import raw_prefix, table_path, upload_dir


def test_raw_prefix():
    assert raw_prefix("bao", "2508.02872") == "raw/bao/2508-02872"
    assert raw_prefix("bao", "2508.02872", 2) == "raw/bao/2508-02872/v2"
    assert raw_prefix("bao", "hep-th/9901001", 1) == "raw/bao/hep-th-9901001/v1"


def test_table_path_validates_name():
    assert table_path("bao", "elements") == "tables/bao/elements.parquet"
    with pytest.raises(ValueError):
        table_path("bao", "nope")


def test_upload_dir_refuses_other_members_folder():
    s = get_settings(env={"MEMBER_NAME": "bao", "HF_TOKEN": "t", "HF_REPO_ID": "x/y"})
    with pytest.raises(ValueError, match="thư mục của mình"):
        upload_dir(s, ".", "raw/nghiem/2508-02872")


@pytest.mark.parametrize("path", ["tables/bao/papers", "raw/bao"])
def test_upload_dir_only_accepts_raw_child_folder(path, tmp_path):
    with patch.object(hf_io, "_api") as api:
        with pytest.raises(ValueError, match="chỉ ghi vào raw"):
            upload_dir(settings(), tmp_path, path)
        api.assert_not_called()


def settings():
    return get_settings(env={"MEMBER_NAME": "bao", "HF_TOKEN": "synthetic-token", "HF_REPO_ID": "test/repo"})


@pytest.mark.parametrize("path", [
    "raw/bao/../nghiem", "/raw/bao", "raw/bao//paper", "raw/bao/./paper",
    "raw/bao/*", "unknown/bao/paper",
])
def test_invalid_paths_rejected_before_network(path, tmp_path):
    with patch.object(hf_io, "_api") as api:
        with pytest.raises(ValueError):
            upload_dir(settings(), tmp_path, path)
        api.assert_not_called()


@pytest.mark.parametrize("version", [0, -1, "2"])
def test_invalid_versions_rejected(version):
    with pytest.raises(ValueError):
        raw_prefix("bao", "2508.02872", version)


def test_member_cannot_escape_table_directory():
    with pytest.raises(ValueError):
        table_path("../nghiem", "papers")


def test_existing_public_repo_is_rejected():
    api = MagicMock()
    api.repo_info.return_value = SimpleNamespace(private=False)
    with patch.object(hf_io, "_api", return_value=api), pytest.raises(ValueError, match="private"):
        hf_io.ensure_repo(settings())
    api.create_repo.assert_called_once_with(repo_id="test/repo", repo_type="dataset", private=True, exist_ok=True)
    api.repo_info.assert_called_once_with(repo_id="test/repo", repo_type="dataset")
    api.update_repo_settings.assert_not_called()


def test_upload_refuses_public_repo(tmp_path):
    api = MagicMock()
    api.repo_info.return_value = SimpleNamespace(private=False)
    with patch.object(hf_io, "_api", return_value=api), pytest.raises(ValueError, match="private"):
        upload_dir(settings(), tmp_path, "raw/bao/2508-02872/v1")
    api.upload_folder.assert_not_called()


def test_private_upload_uses_member_path(tmp_path):
    api = MagicMock()
    api.repo_info.return_value = SimpleNamespace(private=True)
    with patch.object(hf_io, "_api", return_value=api):
        upload_dir(settings(), tmp_path, "raw/bao/2508-02872/v1")
    assert api.upload_folder.call_args.kwargs["path_in_repo"] == "raw/bao/2508-02872/v1"
    assert api.upload_folder.call_args.kwargs["repo_type"] == "dataset"


def test_upload_invalid_table_fails_before_network(tmp_path):
    path = tmp_path / "invalid.parquet"
    path.write_bytes(b"not parquet")
    with patch.object(hf_io, "_api") as api, pytest.raises(Exception):
        hf_io.upload_table(settings(), path, "papers")
    api.assert_not_called()


def test_upload_valid_table_and_download_call_contract(tmp_path):
    path = tmp_path / "papers.parquet"
    write_table(empty_table("papers"), "papers", path)
    api = MagicMock()
    api.repo_info.return_value = SimpleNamespace(private=True)
    with patch.object(hf_io, "_api", return_value=api):
        hf_io.upload_table(settings(), path, "papers")
    assert api.upload_file.call_args.kwargs["path_in_repo"] == "tables/bao/papers.parquet"
    with patch("huggingface_hub.hf_hub_download", return_value=str(path)) as download:
        assert hf_io.download_table(settings(), "nghiem", "papers", tmp_path) == path
    assert download.call_args.kwargs["filename"] == "tables/nghiem/papers.parquet"
    assert download.call_args.kwargs["token"] == "synthetic-token"


def test_download_dir_preserves_nested_selector(tmp_path):
    with patch("huggingface_hub.snapshot_download") as download:
        result = hf_io.download_dir(settings(), "raw/bao/2508-02872", tmp_path)
    assert result == tmp_path / "raw/bao/2508-02872"
    assert download.call_args.kwargs["allow_patterns"] == "raw/bao/2508-02872/*"
