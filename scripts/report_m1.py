"""Export small M1 reporting statistics; never modify the corpus or access APIs."""
import argparse
import json
from pathlib import Path

from src.common.config import ArxivRange
from src.reporting.m1 import snapshot


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--trial',type=Path)
    parser.add_argument('--smoke',type=Path)
    args=parser.parse_args()
    if args.cache.resolve() in args.output.resolve().parents:
        parser.error('Report output must be outside the corpus')
    result=snapshot(args.cache,ArxivRange('2508',2872,7871).ids(),trial=args.trial,smoke=args.smoke)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(result['counts']))


if __name__=='__main__':
    main()
