"""CLI chạy pipeline Parser M2 trên bộ mẫu hoặc toàn Range (docs/m2-cong-viec.md mục 4.4).

Ví dụ:
    python -m scripts.parse_range --data-dir data/m2-sample --plan configs/m2-sample-100.json \\
        --out-dir data/parse --metrics metrics/export.json \\
        --supplement-dir data/m2-bibtex-supplement --roots configs/m2-reviewed-roots.json

``--supplement-dir`` là sidecar bibliography do ``scripts.recover_bibtex_sources`` tạo (khôi phục
``.bib/.bbl`` mà M1 đã lọc); ``--roots`` là file gốc đã review cho các Version ``ambiguous_root``.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.common.config import member_ids
from src.parse.bibtex_input import load_root_reviews
from src.parse.pipeline import run_batch


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-dir",
        "--corpus",
        dest="corpus_dir",
        type=Path,
        required=True,
        help="Thư mục corpus M1 chứa metadata/ và raw/",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("data/parse"),
        help="Thư mục xuất kết quả M2 (tables/, log/versions.jsonl, <key>/done.json)",
    )
    parser.add_argument(
        "--plan",
        type=Path,
        default=None,
        help="File plan bộ mẫu (ví dụ configs/m2-sample-100.json)",
    )
    parser.add_argument(
        "--member",
        type=str,
        default=None,
        help="Tên thành viên trong configs/ranges.toml (lọc theo các ID có mặt trong corpus)",
    )
    parser.add_argument(
        "--id",
        dest="arxiv_ids",
        action="append",
        default=None,
        help="Một hoặc nhiều arXiv ID cụ thể",
    )
    parser.add_argument(
        "--metrics",
        type=Path,
        default=None,
        help="Đường dẫn ghi file metrics JSON (ví dụ metrics/export.json)",
    )
    parser.add_argument(
        "--no-resume",
        action="store_true",
        help="Chạy lại từ đầu, bỏ qua checkpoint done.json đã có",
    )
    parser.add_argument(
        "--allow-fallback",
        action="store_true",
        help="Cờ cũ được giữ để tương thích; pipeline luôn dùng các gói thật",
    )
    parser.add_argument(
        "--supplement-dir",
        type=Path,
        default=None,
        help="Sidecar bibliography của scripts.recover_bibtex_sources (<key>/v<n>/manifest.json)",
    )
    parser.add_argument(
        "--roots",
        type=Path,
        default=None,
        help="File gốc đã review, ví dụ configs/m2-reviewed-roots.json",
    )
    args = parser.parse_args(argv)

    try:
        target_ids: list[str] | None = None
        if args.arxiv_ids:
            target_ids = sorted(set(args.arxiv_ids))
        elif args.member:
            from src.common.schema import publication_key

            meta_dir = args.corpus_dir / "metadata"
            target_ids = [
                aid
                for aid in sorted(member_ids(args.member))
                if (meta_dir / f"{publication_key(aid)}.json").is_file()
            ]

        summary = run_batch(
            args.corpus_dir,
            args.out_dir,
            arxiv_ids=target_ids,
            plan_path=args.plan,
            metrics_path=args.metrics,
            resume=not args.no_resume,
            allow_fallback=args.allow_fallback,
            supplement_dir=args.supplement_dir,
            root_reviews=load_root_reviews(args.roots),
        )
        print(json.dumps(summary, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(f"M2 parse_range failed: {type(exc).__name__}: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
