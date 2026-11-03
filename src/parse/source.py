"""Resolve literal LaTeX compilation paths without executing TeX.

This is the first Parser layer, not a TeX interpreter or a hierarchy parser.
Only active literal input/include commands are expanded. Unsupported control
flow stays visible and produces diagnostics rather than a false success.
Source: https://hcmus-cs-ta.github.io/lab-book/intro-ds/statement/parsing/
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import json
from pathlib import Path
import re

from src.crawl.source import verified_source

ASSEMBLER_VERSION = "1"
_VERBATIM = {"verbatim", "verbatim*", "Verbatim", "lstlisting", "minted", "comment"}
_DEFINITIONS = {"newcommand", "renewcommand", "providecommand", "DeclareRobustCommand",
                "DeclareMathOperator", "newenvironment", "renewenvironment"}
_FLOW = re.compile(r"\\(?:input|include|documentclass|endinput|includeonly)\b")


@dataclass(frozen=True)
class Issue:
    code: str
    severity: str
    file: str
    line: int
    message: str


@dataclass(frozen=True)
class Span:
    """Half-open character offsets in assembled text and original decoded file."""
    output_start: int
    output_end: int
    file: str
    source_start: int
    source_end: int
    line: int


@dataclass
class SourceBundle:
    status: str = "error"
    root: str | None = None
    text: str = ""
    files: list[str] = field(default_factory=list)
    unused_tex_files: list[str] = field(default_factory=list)
    spans: list[Span] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)
    includes: list[dict] = field(default_factory=list)
    checksums: dict[str, str] = field(default_factory=dict)
    assembler_version: str = ASSEMBLER_VERSION

    def to_dict(self) -> dict:
        """JSON-ready working artifact; not an additional Parquet table."""
        return asdict(self)


@dataclass(frozen=True)
class _Command:
    name: str
    start: int
    end: int
    argument: str = ""


@dataclass
class _Scan:
    commands: list[_Command]
    issues: list[Issue]
    stop: int
    ends_document: bool = False


def _control(text: str, start: int) -> tuple[str, int]:
    end = start + 1
    while end < len(text) and (text[end].isalpha() or text[end] == "@"):
        end += 1
    if end == start + 1:
        end = min(end + 1, len(text))
    return text[start + 1:end], end


def _space(text: str, index: int) -> int:
    while index < len(text):
        if text[index].isspace():
            index += 1
        elif text[index] == "%":
            newline = text.find("\n", index)
            index = len(text) if newline < 0 else newline + 1
        else:
            break
    return index


def _group(text: str, index: int, opening: str = "{") -> tuple[str, int]:
    index = _space(text, index)
    if index >= len(text) or text[index] != opening:
        raise ValueError("Expected a literal grouped argument")
    closing = "}" if opening == "{" else "]"
    depth, cursor, chunks = 1, index + 1, []
    while cursor < len(text):
        ch = text[cursor]
        if ch == "\\":
            _, end = _control(text, cursor)
            chunks.append(text[cursor:end]); cursor = end; continue
        if ch == "%":
            cursor = _space(text, cursor); continue
        if ch == opening:
            depth += 1
        elif ch == closing:
            depth -= 1
            if depth == 0:
                return "".join(chunks), cursor + 1
        chunks.append(ch); cursor += 1
    raise ValueError("Unclosed argument")


def _scan(text: str, file: str) -> _Scan:
    """Lex control words, skipping comments, verbatim and definition bodies."""
    result = _Scan([], [], len(text))
    cursor = 0
    conditions: list[bool | None] = []

    def issue(code: str, position: int, message: str, severity: str = "warning"):
        result.issues.append(Issue(code, severity, file, text.count("\n", 0, position) + 1, message))

    while cursor < len(text):
        if text[cursor] == "%":
            cursor = _space(text, cursor); continue
        if text[cursor] != "\\":
            cursor += 1; continue
        start = cursor
        name, cursor = _control(text, cursor)
        active = all(value is True for value in conditions)
        try:
            if name in {"verb", "lstinline"}:
                if cursor < len(text) and text[cursor] == "*":
                    cursor += 1
                if cursor >= len(text) or text[cursor].isspace():
                    raise ValueError("Missing verbatim delimiter")
                end = text.find(text[cursor], cursor + 1)
                if end < 0 or "\n" in text[cursor:end]:
                    raise ValueError("Unclosed inline verbatim")
                cursor = end + 1; continue
            if name in {"begin", "end"}:
                environment, end = _group(text, cursor)
                if name == "begin" and environment in _VERBATIM:
                    closing = "\\end{" + environment + "}"
                    position = text.find(closing, end)
                    if position < 0:
                        raise ValueError("Unclosed verbatim/comment environment")
                    cursor = position + len(closing); continue
                if name == "end" and environment == "document" and active:
                    result.stop, result.ends_document = end, True
                    break
                cursor = end; continue
            if name in _DEFINITIONS or name in {"def", "gdef", "edef", "xdef"}:
                if cursor < len(text) and text[cursor] == "*":
                    cursor += 1
                cursor = _space(text, cursor)
                definition_name = ""
                if name in {"def", "gdef", "edef", "xdef"}:
                    if cursor < len(text) and text[cursor] == "\\":
                        definition_name, cursor = _control(text, cursor)
                    # TeX parameter text ends at the opening body brace.
                    while cursor < len(text) and text[cursor] != "{":
                        if text[cursor] == "%":
                            cursor = _space(text, cursor)
                        else:
                            cursor += 1
                else:
                    if cursor < len(text) and text[cursor] == "\\":
                        definition_name, cursor = _control(text, cursor)
                    else:
                        definition_name, cursor = _group(text, cursor)
                        definition_name = definition_name.lstrip("\\")
                    cursor = _space(text, cursor)
                    while cursor < len(text) and text[cursor] == "[":
                        _, cursor = _group(text, cursor, "[")
                        cursor = _space(text, cursor)
                body, cursor = _group(text, cursor)
                if name.endswith("environment"):
                    tail, cursor = _group(text, cursor); body += tail
                if active and (_FLOW.search(body) or definition_name in
                               {"input", "include", "documentclass", "endinput", "includeonly"}):
                    issue("macro_compilation_path", start, "Macro body controls input/root; expansion is unsupported")
                continue
            if name == "newif":
                cursor = _space(text, cursor)
                if cursor >= len(text) or text[cursor] != "\\":
                    raise ValueError("Missing conditional name")
                _, cursor = _control(text, cursor); continue
            if name == "let":
                for token in range(2):
                    cursor = _space(text, cursor)
                    if token == 1 and cursor < len(text) and text[cursor] == "=":
                        cursor = _space(text, cursor + 1)
                    if cursor < len(text) and text[cursor] == "\\":
                        alias, cursor = _control(text, cursor)
                        if active and alias in {"input", "include", "documentclass", "endinput"}:
                            issue("macro_compilation_path", start, "Aliased compilation command is unsupported")
                    else:
                        cursor += 1
                continue
            if name.startswith("if"):
                value = {"iftrue": True, "iffalse": False}.get(name)
                if active and value is None:
                    issue("unsupported_conditional", start, f"\\{name}: neither branch is expanded")
                conditions.append(value); continue
            if name == "else":
                if not conditions:
                    raise ValueError("Unmatched else")
                if conditions[-1] is not None:
                    conditions[-1] = not conditions[-1]
                continue
            if name == "fi":
                if not conditions:
                    raise ValueError("Unmatched fi")
                conditions.pop(); continue
            if not active:
                continue
            if name in {"catcode", "csname", "scantokens", "import", "subimport",
                        "InputIfFileExists", "IfFileExists", "AtBeginDocument", "AtEndDocument"}:
                issue("unsupported_control", start, f"\\{name} can change the compilation path")
            if name == "endinput":
                tail = text[cursor:].split("\n", 1)[0].split("%", 1)[0]
                if tail.strip():
                    issue("endinput_line_tail", start,
                          "Tokens after endinput on the same line need TeX evaluation")
                result.stop = start; break
            if name == "documentclass":
                result.commands.append(_Command(name, start, cursor)); continue
            if name in {"input", "include", "includeonly"}:
                cursor = _space(text, cursor)
                if cursor < len(text) and text[cursor] == "{":
                    argument, cursor = _group(text, cursor)
                elif name == "input":
                    end = cursor
                    while end < len(text) and not text[end].isspace() and text[end] not in "%{}\\":
                        end += 1
                    argument, cursor = text[cursor:end], end
                else:
                    raise ValueError("Include requires a braced literal filename")
                if not argument.strip() and name != "includeonly":
                    raise ValueError("Empty or dynamic input filename")
                result.commands.append(_Command(name, start, cursor, argument.strip()))
        except ValueError as error:
            issue("invalid_syntax", start, str(error), "error")
            break  # Do not infer active commands after malformed syntax.
    if conditions and not result.ends_document:
        issue("unclosed_conditional", cursor, "Conditional block was not closed", "error")
    return result


def assemble_source(directory: str | Path, *, root_file: str | None = None,
                    require_receipt: bool = False, max_depth: int = 64,
                    max_chars: int = 16 * 1024 * 1024) -> SourceBundle:
    """Assemble one Version, retain provenance, and never mutate source files.

    Literal paths first resolve against the root document's directory, as with
    a TeX working directory; a unique includer-relative fallback is reported.
    Repeated inclusion is preserved, cycles are rejected using the active stack.
    ``ready`` concerns this layer only, not successful hierarchy/BibTeX parsing.
    """
    result = SourceBundle()
    base = Path(directory).absolute()
    if max_depth < 1 or max_chars < 1:
        raise ValueError("Assembly limits must be positive")

    def problem(code, file, message, severity="error", line=1):
        result.issues.append(Issue(code, severity, file, line, message))

    if not base.is_dir() or any(p.is_symlink() for p in (base, *base.parents)):
        problem("invalid_directory", "", "Source directory is missing or uses a symlink")
        return result
    base = base.resolve()
    receipt = None
    if require_receipt or (base / "source.json").exists():
        verified = verified_source(base)
        if verified is None:
            problem("invalid_receipt", "source.json", "Missing receipt, mismatched inventory or checksum")
            return result
        if verified.status == "non_tex":
            result.status = "empty_non_tex"
            return result
        receipt = (base / "source.json").read_bytes()
    paths = sorted(p for p in base.rglob("*") if p.is_file() and p.suffix.lower() == ".tex")
    texts: dict[str, str] = {}
    scans: dict[str, _Scan] = {}
    decode_issues: dict[str, Issue] = {}
    digests: dict[str, str] = {}
    for path in paths:
        relative = path.relative_to(base).as_posix()
        if any(p.is_symlink() for p in (path, *path.parents)):
            problem("symlink", relative, "Symlinked TeX is not accepted")
            return result
        body = path.read_bytes()
        digests[relative] = hashlib.sha256(body).hexdigest()
        if len(body) > max_chars * 4:
            problem("input_limit", relative, "Source file exceeds size limit")
            return result
        try:
            text = body.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = body.decode("latin-1")
            decode_issues[relative] = Issue("encoding_fallback", "warning", relative, 1,
                                           "Decoded as latin-1; verify source encoding")
        texts[relative], scans[relative] = text, _scan(text, relative)
    candidates = [name for name, scan in scans.items()
                  if any(c.name == "documentclass" for c in scan.commands)]
    if root_file is not None:
        if root_file not in candidates:
            problem("invalid_root", root_file, "Explicit root must be an inventoried TeX file with documentclass")
            return result
        selected = root_file
    elif len(candidates) != 1:
        problem("ambiguous_root" if candidates else "missing_root", "",
                f"Expected one root; candidates: {candidates}")
        return result
    else:
        selected = candidates[0]
    result.root = selected
    working = (base / selected).parent
    include_only: set[str] | None = None
    chunks: list[str] = []
    size = 0

    def emit(name, start, end):
        nonlocal size
        if end <= start:
            return
        chunk = texts[name][start:end]
        if size + len(chunk) > max_chars:
            raise ValueError("Expanded source exceeds character limit")
        result.spans.append(Span(size, size + len(chunk), name, start, end,
                                 texts[name].count("\n", 0, start) + 1))
        chunks.append(chunk); size += len(chunk)

    def resolve(argument, name):
        if any(ch in argument for ch in "\\#{}~$"):
            raise ValueError("Dynamic filename is unsupported")
        requested = Path(argument)
        if requested.is_absolute():
            raise ValueError("Absolute include path is forbidden")
        if not requested.suffix:
            requested = requested.with_suffix(".tex")
        candidates = []
        for parent in (working, (base / name).parent):
            path = parent / requested
            if not path.resolve().is_relative_to(base):
                raise ValueError("Include path escapes Version directory")
            if any(p.is_symlink() for p in (path, *path.parents)):
                raise ValueError("Symlink in include path")
            relative = path.resolve().relative_to(base).as_posix()
            if relative in texts and relative not in candidates:
                candidates.append(relative)
        if not candidates:
            raise FileNotFoundError(f"Missing TeX input: {argument}")
        chosen = candidates[0]
        if (working / requested).resolve() != base / chosen:
            problem("relative_to_includer", name, f"Resolved {argument} relative to including file", "info")
        return chosen

    def expand(name, stack):
        nonlocal include_only
        if name in stack:
            raise ValueError("Include cycle: " + " -> ".join([*stack, name]))
        if len(stack) >= max_depth:
            raise ValueError("Maximum include depth exceeded")
        if name not in result.files:
            result.files.append(name)
            result.checksums[name] = digests[name]
            result.issues.extend(scans[name].issues)
            if name in decode_issues:
                result.issues.append(decode_issues[name])
        scan = scans[name]
        position = 0
        for command in scan.commands:
            if command.name == "documentclass":
                if stack:
                    problem("nested_documentclass", name, "Included file declares another document root")
                continue
            if command.name == "includeonly":
                if any(ch in command.argument for ch in "\\#{}~$"):
                    problem("dynamic_includeonly", name, "Dynamic includeonly list is unsupported")
                    continue
                include_only = {value.strip().removesuffix(".tex")
                                for value in command.argument.split(",") if value.strip()}
                continue
            emit(name, position, command.start)
            line = texts[name].count("\n", 0, command.start) + 1
            entry = {"file": name, "line": line, "command": command.name,
                     "argument": command.argument, "target": None, "status": "error"}
            result.includes.append(entry)
            try:
                if (command.name == "include" and include_only is not None
                        and command.argument.removesuffix(".tex") not in include_only):
                    entry["status"] = "excluded_by_includeonly"
                else:
                    target = resolve(command.argument, name)
                    entry["target"] = target
                    stopped = expand(target, [*stack, name])
                    entry["status"] = "expanded"
                    if stopped:
                        return True
            except (ValueError, FileNotFoundError) as error:
                problem("include_error", name, str(error), line=line)
                emit(name, command.start, command.end)
            position = command.end
        emit(name, position, scan.stop)
        return scan.ends_document

    try:
        expand(selected, [])
    except (OSError, ValueError) as error:
        problem("assembly_error", selected, str(error))
    result.text = "".join(chunks)
    result.unused_tex_files = sorted(set(texts) - set(result.files))
    if receipt is not None:
        try:
            expected = json.loads(receipt)["files"]
            if (receipt != (base / "source.json").read_bytes() or verified_source(base) is None
                    or any(expected.get(name) != digest for name, digest in digests.items())):
                problem("source_changed", "source.json", "Source changed while assembling")
        except (OSError, ValueError, KeyError):
            problem("source_changed", "source.json", "Receipt changed while assembling")
    result.status = ("error" if any(i.severity == "error" for i in result.issues) else
                     "needs_review" if any(i.severity == "warning" for i in result.issues) else "ready")
    return result
