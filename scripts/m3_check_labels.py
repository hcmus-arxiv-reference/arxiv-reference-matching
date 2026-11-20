"""Check a filled M3 label sheet and write the clean file to upload (docs/m3-gan-nhan.md, sections 5 and 6).

Checks:
* the six label columns exist; ``confidence`` is ``sure``/``unsure`` on every row (an empty
  value means the row was not labelled yet);
* ``arxiv_id`` is a Publication ID and ``ref_arxiv_id`` is empty or an arXiv ID with no
  ``vN`` suffix and no ``arXiv:`` prefix;
* each ``(arxiv_id, citation_key)`` appears once;
* every non-empty ``ref_arxiv_id`` is a ``references`` row of the same ``arxiv_id``;
* each Publication has at least 20 rows (the course's per-Publication floor).

Extra columns (the sheet's hints) are ignored. With ``--out`` and no errors, the six label
columns are written sorted by ``(arxiv_id, citation_key)``, ready for ``labels/manual/``.

  python scripts/m3_check_labels.py labels-bao-hai.csv --hf-member hai --out bao.csv
  python scripts/m3_check_labels.py labels-bao-crawl-smoke.csv --data-dir data/crawl-smoke
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

LABEL_COLUMNS = ["arxiv_id", "citation_key", "ref_arxiv_id", "confidence", "labeler", "note"]
CONFIDENCE = {"sure", "unsure"}
MIN_ROWS = 20
_ID = re.compile(r"\d{4}\.\d{4,5}|[a-z][a-z.\-]*/\d{7}")


def check(rows: list[dict], columns: list[str], references: dict[str, set[str]] | None) -> tuple[list[str], dict]:
    """Return ``(errors, summary)``; ``references`` maps arxiv_id to its ref_arxiv_id set (None skips that check)."""
    errors = []
    missing = [c for c in LABEL_COLUMNS if c not in columns]
    if missing:
        return [f"thiếu cột: {', '.join(missing)}"], {}
    seen = Counter()
    per_pub = defaultdict(lambda: {"rows": 0, "matched": 0, "empty": 0, "unsure": 0})
    for line, row in enumerate(rows, start=2):  # line 1 is the header
        pid, key = (row.get("arxiv_id") or "").strip(), (row.get("citation_key") or "").strip()
        ref, conf = (row.get("ref_arxiv_id") or "").strip(), (row.get("confidence") or "").strip()
        where = f"dòng {line} ({pid} {key})"
        if not _ID.fullmatch(pid):
            errors.append(f"{where}: arxiv_id không hợp lệ")
        if not key:
            errors.append(f"{where}: citation_key rỗng")
        if conf not in CONFIDENCE:
            errors.append(f"{where}: confidence phải là sure hoặc unsure (trống = chưa gán)")
        if not (row.get("labeler") or "").strip():
            errors.append(f"{where}: labeler rỗng")
        if ref and not _ID.fullmatch(ref):
            errors.append(f"{where}: ref_arxiv_id '{ref}' sai dạng (không có vN, không có 'arXiv:')")
        elif ref and references is not None and ref not in references.get(pid, set()):
            errors.append(f"{where}: ref_arxiv_id {ref} không có trong references của {pid}")
        seen[(pid, key)] += 1
        stats = per_pub[pid]
        stats["rows"] += 1
        stats["matched" if ref else "empty"] += 1
        stats["unsure"] += conf == "unsure"
    errors += [f"{pid} {key}: xuất hiện {n} lần" for (pid, key), n in sorted(seen.items()) if n > 1]
    errors += [f"{pid}: chỉ có {s['rows']} dòng, cần ít nhất {MIN_ROWS}"
               for pid, s in sorted(per_pub.items()) if s["rows"] < MIN_ROWS]
    summary = {"publications": len(per_pub), "rows": len(rows),
               "matched": sum(s["matched"] for s in per_pub.values()),
               "empty": sum(s["empty"] for s in per_pub.values()),
               "unsure": sum(s["unsure"] for s in per_pub.values()),
               "per_publication": dict(sorted(per_pub.items()))}
    return errors, summary


def local_references(data_dir: Path, ids: set[str]) -> dict[str, set[str]]:
    from src.common.corpus import FileCorpus

    corpus = FileCorpus(data_dir)
    return {pid: {r["ref_arxiv_id"] for r in corpus.read_references(pid).references} for pid in ids}


def hf_references(member: str, cache: Path, ids: set[str]) -> dict[str, set[str]]:
    import pyarrow.parquet as pq

    from src.common.config import get_settings
    from src.common.hf_io import download_table

    table = pq.read_table(download_table(get_settings(), member, "references", cache),
                          columns=["arxiv_id", "ref_arxiv_id"])
    refs = defaultdict(set)
    for row in table.to_pylist():
        if row["arxiv_id"] in ids:
            refs[row["arxiv_id"]].add(row["ref_arxiv_id"])
    return {pid: refs.get(pid, set()) for pid in ids}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("sheet", type=Path)
    where = parser.add_mutually_exclusive_group()
    where.add_argument("--data-dir", type=Path, help="local corpus to read references from")
    where.add_argument("--hf-member", help="read tables/<member>/references.parquet from the team HF dataset")
    parser.add_argument("--references", type=Path, help="a references.parquet file")
    parser.add_argument("--out", type=Path, help="write the clean label file here when there is no error")
    args = parser.parse_args(argv)

    with args.sheet.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        rows, columns = list(reader), list(reader.fieldnames or [])
    ids = {(r.get("arxiv_id") or "").strip() for r in rows if _ID.fullmatch((r.get("arxiv_id") or "").strip())}
    if args.data_dir:
        references = local_references(args.data_dir, ids)
    elif args.hf_member:
        references = hf_references(args.hf_member, args.sheet.parent / ".hf-cache", ids)
    elif args.references:
        import pyarrow.parquet as pq

        references = defaultdict(set)
        for row in pq.read_table(args.references, columns=["arxiv_id", "ref_arxiv_id"]).to_pylist():
            references[row["arxiv_id"]].add(row["ref_arxiv_id"])
    else:
        references = None
        print("Cảnh báo: không có nguồn references, bỏ qua kiểm tra ref_arxiv_id có trong references.")

    errors, summary = check(rows, columns, references)
    for error in errors[:200]:
        print("LỖI", error)
    if len(errors) > 200:
        print(f"... và {len(errors) - 200} lỗi khác")
    if summary:
        print(f"{summary['publications']} bài, {summary['rows']} entry: {summary['matched']} khớp, "
              f"{summary['empty']} rỗng, {summary['unsure']} unsure")
        for pid, s in summary["per_publication"].items():
            print(f"  {pid}: {s['rows']} entry, {s['matched']} khớp, {s['empty']} rỗng, {s['unsure']} unsure")
    if errors:
        print(f"{len(errors)} lỗi: sửa rồi chạy lại, chưa upload.")
        return 1
    if args.out:
        clean = sorted(({c: (r.get(c) or "").strip() for c in LABEL_COLUMNS} for r in rows),
                       key=lambda r: (r["arxiv_id"], r["citation_key"]))
        with args.out.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=LABEL_COLUMNS)
            writer.writeheader()
            writer.writerows(clean)
        print(f"Đã ghi {args.out}: sẵn sàng upload lên labels/manual/.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
