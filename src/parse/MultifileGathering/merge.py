"""Gộp mã nguồn của một Version thành chuỗi LaTeX, không ghi lại file nguồn."""

from pathlib import Path

if __name__ == "__main__" and not __package__:
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from src.parse.source import assemble_source


def merge_latex(folder: str | Path, main_file: str | None = None) -> str:
    """Mở rộng input/include đúng vị trí, giữ include lặp và áp dụng includeonly.

    main_file là đường dẫn tương đối trong folder, có thể lấy từ FileTree.
    Nếu không truyền, folder phải có duy nhất một root chứa documentclass.
    Giữ nguyên comment và mã LaTeX chưa chuẩn hóa. Version non_tex đã xác minh
    trả chuỗi rỗng; nguồn lỗi hoặc chưa hỗ trợ đầy đủ gây ValueError.
    """
    bundle = assemble_source(folder, root_file=main_file)
    if bundle.status in {"ready", "empty_non_tex"}:
        return bundle.text
    details = "\n".join(
        f"{issue.file}:{issue.line} [{issue.code}] {issue.message}"
        for issue in bundle.issues if issue.severity in {"warning", "error"}
    )
    raise ValueError(f"Cannot merge LaTeX ({bundle.status}):\n{details}")


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path)
    parser.add_argument("--main-file", help="Đường dẫn tương đối của file main")
    args = parser.parse_args()
    try:
        latex = merge_latex(args.folder, args.main_file)
    except (OSError, ValueError) as error:
        parser.exit(2, f"{error}\n")
    sys.stdout.write(latex)
