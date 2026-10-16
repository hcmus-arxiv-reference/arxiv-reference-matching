"""Schema và kiểm tra bảng Parquet của dự án arXiv.

Nguyên tắc:
- Ba cột đã chốt của Crawling dùng list<string>: papers.authors,
  papers.revised_dates, references.ref_authors; không dùng chuỗi phân cách.
- Không dùng struct/map hoặc JSON blob để chứa bản ghi lồng nhau.
- Ngày lưu dạng chuỗi ISO-8601 (ví dụ "2025-08-04" hoặc "2025-08-04T12:30:00Z").
- Mọi thay đổi file này phải được nhóm trưởng duyệt: cả nhóm phụ thuộc vào nó.

Nguồn Crawling: https://hcmus-cs-ta.github.io/lab-book/intro-ds/statement/crawling/
Hai bảng Crawling đã đối chiếu; bốn bảng còn lại là DỰ THẢO, chưa đóng băng.
validate() chỉ kiểm tra một bảng; không xác minh đủ Version hoặc khóa ngoại.
"""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime
import os
from pathlib import Path
import re
import tempfile

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

# --------------------------------------------------------------------------
# Quy ước chung
# --------------------------------------------------------------------------

LIST_SEP = "; "  # Chỉ còn dùng cho helper tương thích dữ liệu chuỗi cũ.

# arxiv_id: dạng mới "2508.02872" (4 chữ số.4-5 chữ số) hoặc dạng cũ "hep-th/9901001".
# KHÔNG kèm hậu tố phiên bản (v1, v2, ...).
ARXIV_ID_PATTERN = r"^(\d{4}\.\d{4,5}|[a-z\-]+(\.[A-Z]{2})?/\d{7})$"

# element_id: "<publication key>#<discriminant>", ví dụ "2508-02872#s1".
ELEMENT_ID_PATTERN = r"^[^#\s]+#\S+$"

# Chấp nhận ngày hoặc timestamp ISO, sau đó kiểm tra lịch bằng datetime.
DATE_PATTERN = (
    r"\d{4}-\d{2}-\d{2}"
    r"(?:T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?)?"
)

# Các loại Element (cần đối chiếu lại với đề; sửa ở đây là sửa cho cả nhóm).
ELEMENT_KINDS = (
    "document",
    "chapter",
    "section",
    "subsection",
    "subsubsection",
    "paragraph",
    "itemize",
    "item",
    "sentence",
    "formula",
    "figure",
)

PARTITIONS = ("train", "valid", "test")


def publication_key(arxiv_id: str) -> str:
    """Biến arxiv_id thành khóa an toàn cho tên file và element_id.

    "2508.02872" -> "2508-02872";  "hep-th/9901001" -> "hep-th-9901001".
    """
    return arxiv_id.replace("/", "-").replace(".", "-")


def make_element_id(arxiv_id: str, discriminant: str) -> str:
    """Tạo element_id theo quy ước "<publication key>#<discriminant>"."""
    return f"{publication_key(arxiv_id)}#{discriminant}"


def join_list(items: list[str]) -> str:
    """Helper cũ, không dùng cho ba cột list của Crawling.

    Từ chối trường hợp không thể phục hồi bằng split_list().
    """
    if any(not item or LIST_SEP in item for item in items):
        raise ValueError("Không thể mã hóa danh sách thành chuỗi mà không mất dữ liệu")
    return LIST_SEP.join(items)


def split_list(value: str | None) -> list[str]:
    """Đọc chuỗi phân cách cũ; không dùng để đọc các cột list của Crawling."""
    return [] if not value else value.split(LIST_SEP)


# --------------------------------------------------------------------------
# Schema 6 bảng
# --------------------------------------------------------------------------


def _s(name: str, nullable: bool = True) -> pa.Field:
    return pa.field(name, pa.string(), nullable=nullable)


def _strings(name: str) -> pa.Field:
    """Cột list<string> theo đề; null là chưa biết, [] là danh sách rỗng."""
    return pa.field(name, pa.list_(pa.string()))


SCHEMAS: dict[str, pa.Schema] = {
    # Milestone 1
    "papers": pa.schema(
        [
            _s("arxiv_id", nullable=False),
            _s("title"),
            _strings("authors"),
            _s("submission_date"),  # ngày nộp bản v1
            _strings("revised_dates"),  # ngày của v2, v3, ...; [] nếu chỉ có v1
            _s("venue"),
        ]
    ),
    "references": pa.schema(
        [
            _s("arxiv_id", nullable=False),  # bài đi trích dẫn
            _s("ref_arxiv_id", nullable=False),  # bài được trích dẫn (có arXiv ID)
            _s("ref_title"),
            _strings("ref_authors"),
            _s("ref_submission_date"),
            _s("ref_s2_id"),
        ]
    ),
    # Milestone 2
    "elements": pa.schema(
        [
            _s("element_id", nullable=False),
            _s("arxiv_id", nullable=False),
            _s("kind", nullable=False),
            _s("content", nullable=False),  # chuỗi rỗng được phép
        ]
    ),
    "hierarchy": pa.schema(
        [
            _s("arxiv_id", nullable=False),
            pa.field("version", pa.int32(), nullable=False),  # 1, 2, 3, ...
            _s("element_id", nullable=False),
            _s("parent_id"),  # null cho nút gốc (document)
        ]
    ),
    "bibtex": pa.schema(
        [
            _s("arxiv_id", nullable=False),
            _s("citation_key", nullable=False),
            _s("entry_type", nullable=False),
            _s("title"),
            _s("authors"),  # join_list(...)
            _s("year"),  # chuỗi vì dữ liệu bẩn ("2020a", "n.d.")
            _s("doi"),
            _s("journal"),
            _s("url"),
        ]
    ),
    # Milestone 3
    "predictions": pa.schema(
        [
            _s("arxiv_id", nullable=False),
            _s("partition", nullable=False),
            _s("citation_key", nullable=False),
            _s("groundtruth_arxiv_id"),  # null nếu không có reference đúng
            _s("cand_1"),
            _s("cand_2"),
            _s("cand_3"),
            _s("cand_4"),
            _s("cand_5"),
        ]
    ),
}

# Khóa chính: tổ hợp cột không được trùng trong một bảng.
PRIMARY_KEYS: dict[str, list[str]] = {
    "papers": ["arxiv_id"],
    "references": ["arxiv_id", "ref_arxiv_id"],
    "elements": ["element_id"],
    "hierarchy": ["arxiv_id", "version", "element_id"],
    "bibtex": ["arxiv_id", "citation_key"],
    "predictions": ["arxiv_id", "citation_key"],
}

# Cột phải khớp regex (bỏ qua giá trị null ở cột cho phép null).
_PATTERN_CHECKS: dict[str, dict[str, str]] = {
    "papers": {
        "arxiv_id": ARXIV_ID_PATTERN,
    },
    "references": {
        "arxiv_id": ARXIV_ID_PATTERN,
        "ref_arxiv_id": ARXIV_ID_PATTERN,
    },
    "elements": {"element_id": ELEMENT_ID_PATTERN, "arxiv_id": ARXIV_ID_PATTERN},
    "hierarchy": {
        "arxiv_id": ARXIV_ID_PATTERN,
        "element_id": ELEMENT_ID_PATTERN,
        "parent_id": ELEMENT_ID_PATTERN,
    },
    "bibtex": {"arxiv_id": ARXIV_ID_PATTERN},
    "predictions": {
        "arxiv_id": ARXIV_ID_PATTERN,
        "groundtruth_arxiv_id": ARXIV_ID_PATTERN,
        "cand_1": ARXIV_ID_PATTERN,
        "cand_2": ARXIV_ID_PATTERN,
        "cand_3": ARXIV_ID_PATTERN,
        "cand_4": ARXIV_ID_PATTERN,
        "cand_5": ARXIV_ID_PATTERN,
    },
}

# Cột chỉ được nhận một tập giá trị cố định.
_ENUM_CHECKS: dict[str, dict[str, tuple[str, ...]]] = {
    "elements": {"kind": ELEMENT_KINDS},
    "predictions": {"partition": PARTITIONS},
}

_DATE_COLUMNS = {
    "papers": ("submission_date", "revised_dates"),
    "references": ("ref_submission_date",),
}


def _is_iso_date(value: str) -> bool:
    """Kiểm tra toàn bộ chuỗi và ngày thực, không chấp nhận hậu tố rác."""
    if re.fullmatch(DATE_PATTERN, value) is None:
        return False
    try:
        if "T" in value:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
        else:
            date.fromisoformat(value)
    except ValueError:
        return False
    return True


# --------------------------------------------------------------------------
# Kiểm tra
# --------------------------------------------------------------------------


def _count_true(mask: pa.ChunkedArray | pa.Array) -> int:
    return pc.sum(mask).as_py() or 0


def validate(table: pa.Table, name: str) -> list[str]:
    """Trả về lỗi cấu trúc/giá trị/khóa của một bảng, không kiểm tra liên bảng.

    Chỉ chuyển các giá trị ngày duy nhất sang Python để kiểm tra lịch.
    Khóa duy nhất được kiểm tra trong bảng đầu vào, không xuyên các shard.
    """
    if name not in SCHEMAS:
        return [f"Bảng không tồn tại trong schema: {name!r}"]

    schema = SCHEMAS[name]
    errors: list[str] = []

    # 1) Tên cột và kiểu dữ liệu.
    duplicate_columns = [col for col, count in Counter(table.column_names).items() if count > 1]
    if duplicate_columns:
        return [f"[{name}] tên cột trùng: {duplicate_columns}"]
    got = {f.name: f.type for f in table.schema}
    want = {f.name: f.type for f in schema}
    missing = [c for c in want if c not in got]
    extra = [c for c in got if c not in want]
    if missing:
        errors.append(f"[{name}] thiếu cột: {missing}")
    if extra:
        errors.append(f"[{name}] thừa cột: {extra}")
    for col, typ in want.items():
        if col in got and got[col] != typ:
            errors.append(f"[{name}] cột {col!r}: kiểu {got[col]} (cần {typ})")
    if errors:  # sai cấu trúc thì không kiểm tra giá trị nữa
        return errors

    # 2) Null ở cột không cho phép null.
    for field in schema:
        if not field.nullable and table[field.name].null_count:
            errors.append(
                f"[{name}] cột {field.name!r} có {table[field.name].null_count} giá trị null"
            )

    # 2b) Ngày trong cột scalar hoặc từng phần tử của list.
    for col in _DATE_COLUMNS.get(name, ()):
        column = table[col]
        if pa.types.is_list(column.type):
            column = pc.list_flatten(column)
        invalid = [value for value in pc.unique(column).to_pylist()
                   if value is not None and not _is_iso_date(value)]
        if invalid:
            errors.append(f"[{name}] cột {col!r}: ngày ISO không hợp lệ, ví dụ {invalid[:3]}")

    # 3) Định dạng (regex).
    for col, pattern in _PATTERN_CHECKS.get(name, {}).items():
        column = table[col]
        ok = pc.fill_null(pc.match_substring_regex(column, pattern), True)
        bad = pc.invert(ok)
        n_bad = _count_true(bad)
        if n_bad:
            examples = column.filter(bad).slice(0, 3).to_pylist()
            errors.append(f"[{name}] cột {col!r}: {n_bad} giá trị sai định dạng, ví dụ {examples}")

    # 4) Tập giá trị cố định.
    for col, allowed in _ENUM_CHECKS.get(name, {}).items():
        column = table[col]
        bad = pc.invert(pc.is_in(column, value_set=pa.array(list(allowed), pa.string())))
        n_bad = _count_true(bad)
        if n_bad:
            examples = column.filter(bad).slice(0, 3).to_pylist()
            errors.append(f"[{name}] cột {col!r}: {n_bad} giá trị ngoài {allowed}, ví dụ {examples}")

    # 5) Version phải >= 1.
    if name == "hierarchy":
        n_bad = _count_true(pc.less(table["version"], 1))
        if n_bad:
            errors.append(f"[{name}] cột 'version': {n_bad} giá trị < 1")

    # 6) Khóa chính không trùng.
    keys = PRIMARY_KEYS[name]
    n_unique = table.select(keys).group_by(keys).aggregate([]).num_rows
    if n_unique != table.num_rows:
        errors.append(
            f"[{name}] khóa {keys} bị trùng: {table.num_rows - n_unique} dòng thừa"
        )

    return errors


def assert_valid(table: pa.Table, name: str) -> None:
    """Giống validate nhưng ném ValueError nếu có lỗi."""
    errors = validate(table, name)
    if errors:
        raise ValueError("\n".join(errors))


# --------------------------------------------------------------------------
# Tiện ích tạo bảng và đọc/ghi
# --------------------------------------------------------------------------


def empty_table(name: str) -> pa.Table:
    return SCHEMAS[name].empty_table()


def from_records(records: list[dict], name: str) -> pa.Table:
    """Tạo bảng hợp lệ; từ chối trường lạ thay vì âm thầm mất dữ liệu.

    Cột nullable thiếu được điền null; trường API thô phải được ánh xạ
    rõ ràng trước khi gọi hàm này. Truyền dữ liệu theo batch để giới hạn RAM.
    """
    schema = SCHEMAS[name]
    allowed = set(schema.names)
    for index, record in enumerate(records):
        extra = set(record) - allowed
        if extra:
            raise ValueError(f"[{name}] dòng {index}: trường không được khai báo {sorted(extra)}")
    table = pa.Table.from_pylist(records, schema=schema)
    assert_valid(table, name)
    return table


def write_table(table: pa.Table, name: str, path: str | Path) -> None:
    """Kiểm tra rồi thay file nguyên tử; lỗi ghi không phá file đích cũ.

    File tạm nằm cùng thư mục đích để os.replace dùng cùng filesystem.
    Đây không phải khóa chống nhiều process ghi cùng đường dẫn.
    """
    assert_valid(table, name)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            pq.write_table(table, stream, compression="zstd")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def read_table(name: str, path: str | Path) -> pa.Table:
    """Đọc Parquet và kiểm tra theo schema."""
    # Đọc đúng một file, không tự suy ra partition từ thư mục cha có dấu '='.
    table = pq.ParquetFile(path).read()
    assert_valid(table, name)
    return table
