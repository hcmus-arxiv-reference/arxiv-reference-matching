"""Assemble one verified Version for M2; does not generate hierarchy or BibTeX."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.common.json_io import write_json
from src.parse import assemble_source


def main(argv=None) -> int:
    """Write a working JSON artifact outside raw input; non-ready exits with 2."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, required=True,
                        help="Version directory with checksum-verified source.json")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--root", help="Explicit relative root when multiple documentclass files exist")
    args = parser.parse_args(argv)
    if args.output.resolve().is_relative_to(args.source_dir.resolve()):
        parser.error("Output must be outside the source directory")
    try:
        result = assemble_source(args.source_dir, root_file=args.root, require_receipt=True)
        write_json(args.output, result.to_dict())
    except OSError as error:
        parser.exit(2, f"Source assembly I/O failure: {type(error).__name__}\n")
    print(json.dumps({"status": result.status, "root": result.root,
                      "files": len(result.files), "issues": len(result.issues),
                      "output": str(args.output)}, ensure_ascii=False))
    return 0 if result.status in {"ready", "empty_non_tex"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
