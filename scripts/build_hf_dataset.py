"""Dựng dataset Hugging Face để nộp (đề Matching, mục "Final Data Submission").

Gộp bảng của 5 Range thành một dataset với layout đề yêu cầu::

    <out>/README.md                 dataset card, YAML ``configs`` trỏ mỗi bảng tới file của nó
    <out>/data/<bảng>/train-0000i-of-0000n.parquet

Đầu vào là ``<source>/<member>/<bảng>.parquet``, cùng layout với ``tables/<member>/`` trên dataset
private. Thêm ``--from-hf`` để tải layout đó về ``<source>`` trước. Script chỉ ghi cục bộ; việc đẩy
lên dataset public là bước riêng, cần nhóm trưởng đồng ý.

Mỗi bảng được kiểm theo ``src.common.schema`` sau khi gộp. Khóa chính được kiểm trên toàn bảng
(xuyên Range), và các quan hệ giữa bảng được kiểm như sau:

- mọi ``hierarchy.element_id`` và ``parent_id`` có trong ``elements``;
- mọi ``arxiv_id`` của ``references``, ``elements``, ``bibtex`` có trong ``papers``;
- mọi dòng ``predictions`` trỏ tới một dòng ``bibtex``.

Dòng được sắp theo khóa chính, nên cùng đầu vào thì cho cùng file.

Ví dụ::

    python -m scripts.build_hf_dataset --source data/hf-tables --from-hf --out data/hf-public
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from src.common.schema import PRIMARY_KEYS, SCHEMAS, validate

MEMBERS = ("bao", "minh", "nghiem", "hai", "lieu")
TABLES = ("papers", "references", "elements", "hierarchy", "bibtex", "predictions")
# predictions do M3 sinh ra; dataset vẫn dựng được khi chưa có, card ghi rõ bảng còn thiếu.
OPTIONAL = {"predictions"}
SHARD_BYTES = 200 * 1024 * 1024  # theo dung lượng trong bộ nhớ, file Parquet nhỏ hơn nhiều


def load_table(source: Path, name: str, members: tuple[str, ...] = MEMBERS) -> pa.Table | None:
    """Gộp ``<source>/<member>/<name>.parquet`` của các Range; ``None`` nếu không Range nào có."""
    parts = [pq.ParquetFile(path).read() for m in members
             if (path := source / m / f"{name}.parquet").is_file()]
    if not parts:
        return None
    table = pa.concat_tables([p.cast(SCHEMAS[name]) for p in parts])
    return table.sort_by([(column, "ascending") for column in PRIMARY_KEYS[name]])


def _missing(values: pa.ChunkedArray, allowed: pa.ChunkedArray) -> int:
    """Số giá trị khác nhau trong ``values`` không có trong ``allowed``."""
    unique = pc.unique(values)
    return len(unique) - pc.sum(pc.is_in(unique, value_set=pc.unique(allowed))).as_py()


def cross_table_errors(tables: dict[str, pa.Table]) -> list[str]:
    """Lỗi tham chiếu giữa các bảng (validate() của schema chỉ kiểm từng bảng)."""
    errors = []
    papers = tables["papers"]["arxiv_id"]
    for name in ("references", "elements", "bibtex"):
        if (n := _missing(tables[name]["arxiv_id"], papers)):
            errors.append(f"[{name}] {n} arxiv_id không có trong papers")
    ids = tables["elements"]["element_id"]
    for column in ("element_id", "parent_id"):
        if (n := _missing(tables["hierarchy"][column], ids)):
            errors.append(f"[hierarchy] {n} {column} không có trong elements")
    if "predictions" in tables:
        key = lambda t: pc.binary_join_element_wise(t["arxiv_id"], t["citation_key"], "\x1f")
        if (n := _missing(key(tables["predictions"]), key(tables["bibtex"]))):
            errors.append(f"[predictions] {n} (arxiv_id, citation_key) không có trong bibtex")
    return errors


def write_shards(table: pa.Table, directory: Path) -> list[Path]:
    """Ghi bảng thành ``train-0000i-of-0000n.parquet``, mỗi shard khoảng ``SHARD_BYTES``."""
    directory.mkdir(parents=True, exist_ok=True)
    for old in directory.glob("*.parquet"):
        old.unlink()
    # Không tạo shard rỗng: số shard không vượt quá số dòng.
    count = max(1, min(table.num_rows, math.ceil(table.nbytes / SHARD_BYTES)))
    rows = math.ceil(table.num_rows / count) if table.num_rows else 0
    paths = []
    for i in range(count):
        path = directory / f"train-{i:05d}-of-{count:05d}.parquet"
        pq.write_table(table.slice(i * rows, rows), path, compression="zstd")
        paths.append(path)
    return paths


def dataset_card(counts: dict[str, int]) -> str:
    """README.md có YAML ``configs`` (mỗi bảng một config, split ``train``) và mô tả bảng."""
    configs = "".join(
        f"- config_name: {name}\n  data_files:\n  - split: train\n    path: data/{name}/*.parquet\n"
        for name in TABLES if name in counts)
    rows = "\n".join(f"| `{name}` | {counts[name]:,} |".replace(",", ".") if name in counts
                     else f"| `{name}` | chưa có |" for name in TABLES)
    columns = "\n".join(f"- `{name}`: " + ", ".join(f"`{f.name}`" for f in SCHEMAS[name])
                        for name in TABLES)
    return f"""---
pretty_name: arXiv Reference Matching (HCMUS, nhóm 3 KHDL24)
language:
- en
- vi
size_categories:
- 10M<n<100M
configs:
{configs}---

# arXiv Reference Matching

Dữ liệu của đồ án Nhập môn Khoa học Dữ liệu (HCMUS): 24.977 Publication arXiv thuộc 5 dải ID,
metadata và reference Semantic Scholar có arXiv ID (Milestone 1), mã nguồn LaTeX được parse thành
cây phân cấp và BibTeX entry đã khử trùng lặp (Milestone 2), và kết quả ghép BibTeX entry với
reference (Milestone 3).

Mã nguồn: <https://github.com/hcmus-arxiv-reference/arxiv-reference-matching>.
Báo cáo: <https://hcmus-arxiv-reference.github.io/Jupyter-Notebook-report-for-mile1/>.

## Bảng

| Bảng | Số dòng |
|---|---|
{rows}

Mỗi bảng là một config, đọc bằng `datasets.load_dataset("<repo>", "<bảng>", split="train")`.

Cột:

{columns}

- Ba cột `authors`, `revised_dates`, `ref_authors` là list of strings; mọi cột khác là kiểu nguyên thủy.
- `element_id` có dạng `<publication key>#<kind>-<hash>`; một Element giống hệt nhau giữa các
  Version chỉ có một dòng trong `elements`.
- Một dòng `hierarchy` là một cạnh nút → cha của một Version.
- `bibtex` chỉ giữ entry được trích dẫn trong bài.
"""


def build(source: Path, out: Path) -> dict[str, object]:
    """Gộp, kiểm và ghi dataset; trả số dòng và lỗi. Không ghi gì nếu có lỗi."""
    tables, errors = {}, []
    for name in TABLES:
        table = load_table(source, name)
        if table is None:
            if name not in OPTIONAL:
                errors.append(f"[{name}] không có file nào trong {source}")
            continue
        errors += validate(table, name)
        tables[name] = table
    if not errors:
        errors += cross_table_errors(tables)
    counts = {name: t.num_rows for name, t in tables.items()}
    if errors:
        return {"counts": counts, "errors": errors, "files": []}
    files = []
    for name, table in tables.items():
        files += [str(p.relative_to(out)) for p in write_shards(table, out / "data" / name)]
    (out / "README.md").write_text(dataset_card(counts), encoding="utf-8")
    return {"counts": counts, "errors": [], "files": files}


def download(source: Path) -> None:
    """Tải ``tables/<member>/<bảng>.parquet`` từ dataset private về ``<source>/<member>/``."""
    from src.common.config import get_settings
    from src.common.hf_io import download_table

    settings = get_settings()
    for member in MEMBERS:
        for name in TABLES:
            try:
                path = download_table(settings, member, name, source / ".hf")
            except Exception:
                if name in OPTIONAL:
                    continue
                raise
            target = source / member / f"{name}.parquet"
            target.parent.mkdir(parents=True, exist_ok=True)
            Path(path).replace(target)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--source", type=Path, required=True, help="<source>/<member>/<bảng>.parquet")
    parser.add_argument("--out", type=Path, required=True, help="Thư mục dataset sẽ ghi")
    parser.add_argument("--from-hf", action="store_true", help="Tải tables/<member>/ từ dataset private trước")
    args = parser.parse_args(argv)
    if args.from_hf:
        download(args.source)
    report = build(args.source, args.out)
    print(json.dumps(report, ensure_ascii=False, indent=1))
    return 1 if report["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
