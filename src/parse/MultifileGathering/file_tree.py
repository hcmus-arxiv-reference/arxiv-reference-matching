"""Find a main source file and save its literal LaTeX dependencies as JSON."""

from dataclasses import asdict, dataclass
import json
from pathlib import Path

if __name__ == "__main__" and not __package__:
    import sys

    # Allow running this file directly, including from outside the repo.
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from src.parse.source import _group, _input_names, _scan, _space

DEFAULT_OUTPUT = Path(__file__).resolve().parent / "output" / "file_tree.json"


@dataclass
class FileTree:
    """Paths relative to the source folder, with each dependency listed once."""

    main_file: str | None
    input_files: tuple[str, ...]


def _document_class(text: str, offset: int) -> str | None:
    """Read the class after an active documentclass command, including options."""
    try:
        offset = _space(text, offset)
        if offset < len(text) and text[offset] == "[":
            _, offset = _group(text, offset, "[")
        name, _ = _group(text, offset)
        return name.strip()
    except ValueError:
        return None


def _gather_inputs(main: Path, base: Path, scans: dict, files: set[Path],
                   *, recursive: bool = True) -> tuple[str, ...]:
    """Follow literal inputs in source order, applying includeonly to includes."""
    inputs = []
    input_names = set()
    visited = {main.resolve()}
    include_only = None
    pending = [(main, iter(scans[main].commands))] if main in scans else []
    while pending:
        path, commands = pending[-1]
        command = next(commands, None)
        if command is None:
            pending.pop()
            continue
        if command.name == "includeonly":
            # Macro expansion is unsupported; only apply literal filename lists.
            if not any(character in command.argument for character in "\\#{}~$"):
                include_only = {name.strip().removesuffix(".tex")
                                for name in command.argument.split(",") if name.strip()}
            continue
        if command.name not in {"input", "include"}:
            continue
        if (command.name == "include" and include_only is not None
                and command.argument.removesuffix(".tex") not in include_only):
            continue
        try:
            requested_names = _input_names(command.argument)
        except ValueError:
            continue
        # TeX resolves against the main directory; allow nested local files too.
        child = None
        for parent in (main.parent, path.parent):
            for requested in requested_names:
                candidate = (parent / requested).resolve()
                if (not Path(requested).is_absolute() and candidate.is_relative_to(base)
                        and candidate in files):
                    child = candidate
                    break
            if child is not None:
                break
        if child is None:
            continue
        name = child.relative_to(base).as_posix()
        if child != main and name not in input_names and (recursive or len(pending) == 1):
            inputs.append(name)
            input_names.add(name)
        if child not in visited:
            visited.add(child)
            if child in scans:
                pending.append((child, iter(scans[child].commands)))
    return tuple(inputs)


def build_file_tree(
    folder: str | Path, output_path: str | Path | None = None
) -> FileTree:
    """Scan a folder recursively, return its file tree and write a JSON copy.

    A single file is always the main file. Otherwise, prefer documentclass,
    then the exact filename main.tex, then input, then include. Within a priority
    group, main.tex wins ties before preferring article classes over standalone
    and beamer, then files in the source root, then more unique direct TeX inputs,
    then more recursive TeX dependencies. Relative filename breaks remaining ties.
    Empty folders and folders without a matching candidate produce a null main.
    Output defaults to output/file_tree.json beside this module, regardless of cwd.
    Generated JSON is ignored on reruns.
    """
    base = Path(folder).resolve()
    if not base.is_dir():
        raise NotADirectoryError(base)
    output = Path(output_path).resolve() if output_path is not None else DEFAULT_OUTPUT
    files = sorted(
        path for path in base.rglob("*")
        if path.is_file() and path.resolve().is_relative_to(base)
        and path.resolve() not in {output, base / "file_tree.json"}
    )
    scans = {}
    document_classes = {}
    for path in files:
        if path.suffix.lower() != ".tex":
            continue
        body = path.read_bytes()
        try:
            text = body.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = body.decode("latin-1")
        scans[path] = _scan(text, path.relative_to(base).as_posix())
        for command in scans[path].commands:
            if command.name == "documentclass":
                document_classes[path] = _document_class(text, command.end)
                break

    main = files[0] if len(files) == 1 else None
    candidate_inputs = {}
    if len(files) > 1:
        for command in ("documentclass", "main.tex", "input", "include"):
            if command == "main.tex":
                candidates = [path for path in scans if path.name == "main.tex"]
            else:
                candidates = [path for path, scan in scans.items()
                              if any(item.name == command for item in scan.commands)]
            if candidates:
                file_set = set(files)
                candidate_inputs = {
                    path: _gather_inputs(path, base, scans, file_set) for path in candidates
                }
                main = min(candidates, key=lambda path: (
                    path.name != "main.tex",
                    document_classes.get(path) in {"standalone", "beamer"},
                    path.parent != base,
                    -sum(Path(name).suffix.lower() == ".tex" for name in
                         _gather_inputs(path, base, scans, file_set, recursive=False)),
                    -sum(Path(name).suffix.lower() == ".tex" for name in candidate_inputs[path]),
                    path.relative_to(base).as_posix(),
                ))
                break

    result = FileTree(
        main.relative_to(base).as_posix() if main is not None else None,
        candidate_inputs.get(main, ()),
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(asdict(result), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path)
    parser.add_argument("-o", "--output", type=Path, help=f"default: {DEFAULT_OUTPUT}")
    args = parser.parse_args()
    build_file_tree(args.folder, args.output)
