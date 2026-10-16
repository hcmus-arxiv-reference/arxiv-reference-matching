"""Đọc/ghi dữ liệu làm việc trên Hugging Face dataset PRIVATE của nhóm.

Quy ước đường dẫn trong repo:
    raw/<member>/<publication key>/v<n>/...   (file .tex, .bib thô)
    tables/<member>/<tên bảng>.parquet        (bảng đã xử lý của từng người)

Mỗi thành viên chỉ GHI vào thư mục của mình (member), nên không ghi đè nhau.
huggingface_hub được import trễ (trong hàm) để phần còn lại chạy được khi chưa cài.
"""

from __future__ import annotations

from pathlib import Path
import re

from .config import Settings
from .schema import ARXIV_ID_PATTERN, SCHEMAS, publication_key, read_table

# --------------------------------------------------------------------------
# Đường dẫn trong repo (thuần logic, dễ test)
# --------------------------------------------------------------------------


def _member_name(member: str) -> str:
    """Tên thành viên là một đoạn đường dẫn, không chứa '/' hoặc '..'."""
    if not isinstance(member, str) or re.fullmatch(r"[A-Za-z0-9_-]+", member) is None:
        raise ValueError(f"Tên thành viên không hợp lệ: {member!r}")
    return member


def _repo_path(path: str) -> list[str]:
    """Từ chối đường dẫn tuyệt đối, đoạn rỗng/dot và glob trong selector tải."""
    parts = path.split("/")
    if (any(part in ("", ".", "..") for part in parts)
            or any(char in path for char in "\\*?[]")
            or parts[0] not in ("raw", "tables") or len(parts) < 2):
        raise ValueError(f"Đường dẫn repo không hợp lệ: {path!r}")
    _member_name(parts[1])
    return parts


def raw_prefix(member: str, arxiv_id: str, version: int | None = None) -> str:
    """raw/<member>/<publication key>[/v<n>]"""
    _member_name(member)
    if re.fullmatch(ARXIV_ID_PATTERN, arxiv_id) is None:
        raise ValueError(f"arxiv_id không hợp lệ: {arxiv_id!r}")
    if version is not None and (type(version) is not int or version < 1):
        raise ValueError("version phải là số nguyên >= 1")
    base = f"raw/{member}/{publication_key(arxiv_id)}"
    return base if version is None else f"{base}/v{version}"


def table_path(member: str, name: str) -> str:
    """tables/<member>/<name>.parquet"""
    if name not in SCHEMAS:
        raise ValueError(f"Bảng không tồn tại trong schema: {name!r}")
    return f"tables/{_member_name(member)}/{name}.parquet"


# --------------------------------------------------------------------------
# Thao tác với Hugging Face
# --------------------------------------------------------------------------


def _api(settings: Settings):
    from huggingface_hub import HfApi

    settings.require_hf()
    return HfApi(token=settings.hf_token)


def ensure_repo(settings: Settings) -> None:
    """Tạo private repo nếu thiếu; từ chối nếu repo đã có là public.

    Không tự thay visibility của repo có sẵn.
    """
    api = _api(settings)
    api.create_repo(
        repo_id=settings.hf_repo_id, repo_type="dataset", private=True, exist_ok=True
    )
    _assert_private(api, settings)


def _assert_private(api, settings: Settings) -> None:
    """Xác minh visibility trước khi đẩy dữ liệu lên repo."""
    info = api.repo_info(repo_id=settings.hf_repo_id, repo_type="dataset")
    if info.private is not True:
        raise ValueError("Dataset phải là private trước khi upload dữ liệu.")


def upload_dir(settings: Settings, local_dir: str | Path, path_in_repo: str, message: str | None = None) -> None:
    """Đẩy thư mục thô vào raw/<member>/...; bảng dùng upload_table()."""
    parts = _repo_path(path_in_repo)
    if parts[0] != "raw" or len(parts) < 3:
        raise ValueError("upload_dir chỉ ghi vào raw/<MEMBER_NAME>/...; bảng dùng upload_table().")
    if parts[1] != settings.member:
        raise ValueError(
            f"Chỉ được ghi vào thư mục của mình ({settings.member!r}), nhận {path_in_repo!r}"
        )
    api = _api(settings)
    _assert_private(api, settings)
    api.upload_folder(
        folder_path=str(local_dir),
        path_in_repo=path_in_repo,
        repo_id=settings.hf_repo_id,
        repo_type="dataset",
        commit_message=message or f"upload {path_in_repo}",
    )


def download_dir(settings: Settings, path_in_repo: str, local_dir: str | Path) -> Path:
    """Tải một thư mục con của repo về local_dir (giữ nguyên cấu trúc đường dẫn)."""
    _repo_path(path_in_repo)
    from huggingface_hub import snapshot_download

    settings.require_hf()
    snapshot_download(
        repo_id=settings.hf_repo_id,
        repo_type="dataset",
        allow_patterns=f"{path_in_repo.rstrip('/')}/*",
        local_dir=str(local_dir),
        token=settings.hf_token,
    )
    return Path(local_dir) / path_in_repo


def upload_table(settings: Settings, local_file: str | Path, name: str) -> None:
    """Đẩy một file Parquet của mình lên tables/<member>/<name>.parquet."""
    path_in_repo = table_path(settings.member, name)
    read_table(name, local_file)  # Chặn bảng sai trước khi gọi mạng.
    api = _api(settings)
    _assert_private(api, settings)
    api.upload_file(
        path_or_fileobj=str(local_file),
        path_in_repo=path_in_repo,
        repo_id=settings.hf_repo_id,
        repo_type="dataset",
        commit_message=f"upload table {name} ({settings.member})",
    )


def download_table(settings: Settings, member: str, name: str, local_dir: str | Path) -> Path:
    """Tải bảng của một thành viên bất kỳ (nhóm trưởng dùng để QA)."""
    from huggingface_hub import hf_hub_download

    settings.require_hf()
    path = hf_hub_download(
        repo_id=settings.hf_repo_id,
        repo_type="dataset",
        filename=table_path(member, name),
        local_dir=str(local_dir),
        token=settings.hf_token,
    )
    return Path(path)
