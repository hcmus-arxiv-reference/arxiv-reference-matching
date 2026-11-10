"""Export small M1 reporting statistics; never modify the corpus or access APIs."""
import argparse
import json
from pathlib import Path

from src.common.config import member_ids
from src.reporting.m1 import snapshot


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--trial',type=Path)
    parser.add_argument('--smoke',type=Path)
    parser.add_argument('--member',default='bao',help='Range trong configs/ranges.toml (mặc định: bao)')
    parser.add_argument('--ids-file',type=Path,help='danh sách ID thay cho cả Range (lượt chạy thử)')
    parser.add_argument('--benchmark',type=Path,help='benchmark_total.json của src.merge_benchmarks')
    parser.add_argument('--crawl-note',help='mô tả lượt crawl tạo ra corpus này')
    args=parser.parse_args(argv)
    if args.cache.resolve() in args.output.resolve().parents:
        parser.error('Report output must be outside the corpus')
    if args.ids_file:
        ids=[l.strip() for l in args.ids_file.read_text().splitlines() if l.strip() and not l.startswith('#')]
    else:
        ids=list(member_ids(args.member))
    benchmark=json.loads(args.benchmark.read_text()) if args.benchmark else None
    result=snapshot(args.cache,ids,member=args.member,trial=args.trial,smoke=args.smoke,
                    benchmark=benchmark,crawl_note=args.crawl_note)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(result['counts']))


if __name__=='__main__':
    main()
