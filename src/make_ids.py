"""
make_ids.py - Sinh danh sách arXiv ID LIÊN TỤC từ ID đầu đến ID cuối (gồm cả hai đầu).

Ví dụ:
    python make_ids.py 2310.00001 2310.05000 -o ids.txt
    python make_ids.py 2310.00001 2310.05000 --chunk 500 -o ids.txt
        -> tạo ids_part_01.txt, ids_part_02.txt, ... (mỗi file tối đa 500 ID)
    python make_ids.py hep-th/9901001 hep-th/9901120 -o ids.txt     (ID kiểu cũ)

Lưu ý:
    - Số phải có đủ số 0 ở đầu: 2310.00001 (đúng), 2310.1 (sai).
    - ID đầu và ID cuối phải cùng tháng (cùng phần trước số thứ tự).
      Nếu dải của bạn đi qua nhiều tháng, hãy chạy mỗi tháng một lần rồi nối file.
"""
import argparse
import re
import sys
from pathlib import Path

NEW_STYLE = re.compile(r"^(?P<prefix>\d{4}\.)(?P<num>\d{4,5})$")                 # 2310.12345
OLD_STYLE = re.compile(r"^(?P<prefix>[a-z\-]+(?:\.[A-Z]{2})?/\d{4})(?P<num>\d{3})$")  # hep-th/9901001


def parse(arxiv_id):
    """Tách ID thành (phần đầu, số thứ tự dạng chữ). Ví dụ 2310.00001 -> ('2310.', '00001')."""
    text = arxiv_id.strip()
    for pattern in (NEW_STYLE, OLD_STYLE):
        m = pattern.match(text)
        if m:
            return m.group("prefix"), m.group("num")
    raise ValueError(
        f"cannot read '{arxiv_id}' as an arXiv ID (expected e.g. 2310.00001 or hep-th/9901001; "
        "use ID without version suffix and keep leading zeros)"
    )


def build_range(start, end):
    prefix_a, num_a = parse(start)
    prefix_b, num_b = parse(end)
    if prefix_a != prefix_b:
        raise ValueError(
            f"start and end are in different months ('{prefix_a}' vs '{prefix_b}'). "
            "Make one range per month and join the files."
        )
    if len(num_a) != len(num_b):
        raise ValueError("start and end numbers must have the same number of digits (keep leading zeros)")
    first, last = int(num_a), int(num_b)
    if first > last:
        raise ValueError("start ID comes after end ID")
    width = len(num_a)
    return [f"{prefix_a}{i:0{width}d}" for i in range(first, last + 1)]


def main():
    ap = argparse.ArgumentParser(description="Generate a continuous list of arXiv IDs")
    ap.add_argument("start", help="ID đầu, ví dụ 2310.00001")
    ap.add_argument("end", help="ID cuối (tính cả), ví dụ 2310.05000")
    ap.add_argument("-o", "--out", default=None, help="file kết quả (không có thì in ra màn hình)")
    ap.add_argument("--chunk", type=int, default=0, help="chia thành các file, mỗi file tối đa N ID")
    args = ap.parse_args()

    try:
        ids = build_range(args.start, args.end)
    except ValueError as exc:
        ap.error(str(exc))

    print(f"{len(ids)} IDs: {ids[0]} ... {ids[-1]}", file=sys.stderr)

    if args.chunk and args.chunk > 0:
        base = Path(args.out or "ids.txt")
        n_parts = 0
        for n_parts, i in enumerate(range(0, len(ids), args.chunk), 1):
            part = base.with_name(f"{base.stem}_part_{n_parts:02d}{base.suffix}")
            part.write_text("\n".join(ids[i:i + args.chunk]) + "\n", encoding="utf-8")
            print(f"wrote {part} ({len(ids[i:i + args.chunk])} IDs)", file=sys.stderr)
    elif args.out:
        Path(args.out).write_text("\n".join(ids) + "\n", encoding="utf-8")
        print(f"wrote {args.out}", file=sys.stderr)
    else:
        print("\n".join(ids))


if __name__ == "__main__":
    main()