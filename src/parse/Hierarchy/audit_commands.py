"""Offline engineering QA audit of unsupported LaTeX commands and environments.

Scans the local corpus across two explicitly separate views:
1. Reachable pipeline diagnostics: file_tree -> merge_latex -> native HierarchyEngine.
2. Source-wide lexical inventory: recursive scan over all .tex/.sty/.cls files,
   skipping comments, verbatim/literal environments, and inline \\verb bodies;
   extracting local macro/environment definitions, calls, and macro-body tokens.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from collections.abc import Mapping
import csv
from dataclasses import asdict, dataclass, field
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time
from typing import Any

# Default directories and configuration
REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_RAW_DIR = REPO_ROOT / "data/arxiv_crawl_20261024/raw"
DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parent / "output/undefined_commands_all"
DEFAULT_MANIFEST = DEFAULT_OUTPUT_DIR / "manifest.json"
DEFAULT_MAPPING = Path(__file__).resolve().parent / "mapping.json"

# Block literal / verbatim environments where TeX commands are completely inactive.
# NOTE: 'alltt' executes LaTeX commands and is intentionally excluded from literal environments.
LITERAL_ENVIRONMENTS = {
    "verbatim",
    "verbatim*",
    "Verbatim",
    "lstlisting",
    "minted",
    "comment",
    "filecontents",
    "filecontents*",
    "rawhtml",
}

# Declarations recognized in TeX / LaTeX
KNOWN_DEF_COMMANDS = {
    "\\newcommand",
    "\\renewcommand",
    "\\providecommand",
    "\\DeclareRobustCommand",
    "\\newcommand*",
    "\\renewcommand*",
    "\\providecommand*",
    "\\DeclareRobustCommand*",
    "\\def",
    "\\gdef",
    "\\edef",
    "\\xdef",
    "\\newenvironment",
    "\\renewenvironment",
    "\\newtheorem",
    "\\newtheorem*",
    "\\DeclareMathOperator",
    "\\DeclareMathOperator*",
}

# Primitives and control flow handled directly by C++ HierarchyEngine without mapping rules.
# NOTE: Unknown \if... conditionals emit unhandled_command diagnostics in the engine when active.
CORE_RUNTIME_HANDLED = {
    "\\begin",
    "\\end",
    "\\verb",
    "\\verb*",
    "\\appendix",
    "\\endinput",
    "\\iftrue",
    "\\iffalse",
    "\\else",
    "\\fi",
    "\\documentclass",
    "\\newtheorem", "\\newtheorem*", "\\newif",
    "\\begingroup", "\\endgroup", "\\bgroup", "\\egroup",
    "\\(", "\\)", "\\[", "\\]",
    # Builtin definition forms handled in C++ definition scanner:
    "\\newcommand",
    "\\renewcommand",
    "\\providecommand",
    "\\DeclareRobustCommand",
    "\\newcommand*",
    "\\renewcommand*",
    "\\providecommand*",
    "\\DeclareRobustCommand*",
    "\\newenvironment",
    "\\renewenvironment",
    "\\def",
    "\\gdef",
    "\\edef",
    "\\xdef",
}

# Context-dependent safe next-action suggestions (advisory only, not automated mapping edits)
SAFE_ACTION_HEURISTICS: dict[str, str] = {
    # Layout and spacing discards
    "\\thispagestyle": "discard",
    "\\pagestyle": "discard",
    "\\newpage": "discard",
    "\\clearpage": "discard",
    "\\cleardoublepage": "discard",
    "\\vspace": "discard",
    "\\vspace*": "discard",
    "\\hspace": "discard",
    "\\hspace*": "discard",
    "\\noindent": "discard",
    "\\indent": "discard",
    "\\centering": "discard",
    "\\raggedright": "discard",
    "\\raggedleft": "discard",
    "\\setstretch": "discard",
    "\\linespread": "discard",
    "\\bigskip": "discard",
    "\\medskip": "discard",
    "\\smallskip": "discard",
    # Single-argument styling unwraps
    "\\textbf": "unwrap",
    "\\textit": "unwrap",
    "\\emph": "unwrap",
    "\\texttt": "unwrap",
    "\\textsf": "unwrap",
    "\\textsc": "unwrap",
    "\\textsl": "unwrap",
    "\\underline": "unwrap",
    # Semantic references
    "\\cite": "preserve",
    "\\ref": "preserve",
    "\\pageref": "preserve",
    "\\eqref": "preserve",
    "\\url": "preserve",
    "\\href": "preserve",
    "\\label": "preserve",
}

SAFE_ENV_HEURISTICS: dict[str, str] = {
    "center": "transparent",
    "flushleft": "transparent",
    "flushright": "transparent",
    "minipage": "transparent",
    "adjustbox": "transparent",
    "figure*": "figure",
    "table*": "figure",
    "tabular*": "figure",
    "sidewaystable": "figure",
    "sidewaysfigure": "figure",
    "wrapfigure": "figure",
    "subfigure": "figure",
    "subtable": "figure",
    "proof": "transparent",
    "quote": "transparent",
    "quotation": "transparent",
}


@dataclass
class DefinitionEvidence:
    name: str
    target_type: str  # 'command' or 'environment'
    def_cmd: str  # '\newcommand', '\def', etc.
    publication: str
    version: int
    file: str
    line: int
    signature: str
    excerpt: str


@dataclass
class OccurrenceExample:
    name: str
    target_type: str  # 'command' or 'environment'
    publication: str
    version: int
    file: str
    line: int
    source_scope: str  # 'document_body', 'macro_body', 'preamble', 'fragment_or_preamble', '<merged>'
    excerpt: str
    byte_offset: int | None = None
    char_offset: int | None = None


@dataclass
class VersionAuditResult:
    publication: str
    version: int
    status: str
    source_signature: str = ""
    error: str | None = None
    receipt_kind: str | None = None
    receipt_status: str | None = None
    discovered_files: int = 0
    inspected_files: int = 0
    unreadable_files: int = 0
    tex_files_count: int = 0
    sty_cls_count: int = 0
    main_file: str | None = None
    merged_bytes: int = 0
    # Diagnostics from reachable pipeline
    diagnostic_counts: dict[str, int] = field(default_factory=dict)
    unhandled_commands_diag: dict[str, int] = field(default_factory=dict)
    unhandled_environments_diag: dict[str, int] = field(default_factory=dict)
    unexpanded_definitions_diag: int = 0
    diagnostic_examples: list[dict[str, Any]] = field(default_factory=list)
    # Lexical inventory counts & per-tag files
    source_commands: dict[str, int] = field(default_factory=dict)
    source_commands_files: dict[str, list[str]] = field(default_factory=dict)
    source_environments: dict[str, int] = field(default_factory=dict)
    source_environments_files: dict[str, list[str]] = field(default_factory=dict)
    macro_body_commands: dict[str, int] = field(default_factory=dict)
    macro_body_files: dict[str, list[str]] = field(default_factory=dict)
    macro_body_environments: dict[str, int] = field(default_factory=dict)
    macro_body_environment_files: dict[str, list[str]] = field(default_factory=dict)
    # Evidence and examples (bounded <= 3 per tag)
    definitions: list[dict[str, Any]] = field(default_factory=list)
    examples: list[dict[str, Any]] = field(default_factory=list)
    file_warnings: list[dict[str, str]] = field(default_factory=list)


def is_escaped_percent(text: str, pos: int) -> bool:
    """Check if % at pos is preceded by an odd number of backslashes."""
    if pos < 0 or pos >= len(text) or text[pos] != "%":
        return False
    bs_count = 0
    idx = pos - 1
    while idx >= 0 and text[idx] == "\\":
        bs_count += 1
        idx -= 1
    return (bs_count % 2) == 1


def read_text_safe(path: Path) -> tuple[str, str | None]:
    """Read file content with utf-8-sig fallback to latin-1."""
    data = path.read_bytes()
    try:
        return data.decode("utf-8-sig"), None
    except UnicodeDecodeError:
        return data.decode("latin-1"), "latin-1 fallback decode"


def compute_dir_signature(directory: Path) -> str:
    """Deterministic hash of relative file paths, sizes, and mtimes for change detection."""
    entries = []
    for p in sorted(directory.rglob("*")):
        if p.is_file():
            stat = p.stat()
            entries.append(f"{p.relative_to(directory).as_posix()}:{stat.st_size}:{stat.st_mtime_ns}")
    return hashlib.sha256("\n".join(entries).encode("utf-8")).hexdigest()


def skip_whitespace_and_comments(text: str, pos: int) -> int:
    """Advance past whitespace and full TeX comment lines."""
    n = len(text)
    while pos < n:
        if text[pos].isspace():
            pos += 1
        elif text[pos] == "%" and not is_escaped_percent(text, pos):
            nl = text.find("\n", pos)
            pos = n if nl == -1 else nl + 1
        else:
            break
    return pos


def parse_balanced_group(text: str, start_pos: int, opening: str = "{") -> tuple[str, int] | None:
    """Parse balanced argument in `{...}` or `[...]`, respecting comments and nested braces."""
    n = len(text)
    idx = skip_whitespace_and_comments(text, start_pos)
    if idx >= n or text[idx] != opening:
        return None

    closing = "}" if opening == "{" else "]"
    depth = 1
    braces = 0  # inside [...] keep track of braces {...}
    body_start = idx + 1
    idx += 1

    while idx < n:
        c = text[idx]
        if c == "%" and not is_escaped_percent(text, idx):
            nl = text.find("\n", idx)
            idx = n if nl == -1 else nl + 1
            continue

        if c == "\\":
            idx += 1
            if idx < n and (text[idx].isalpha() or text[idx] == "@"):
                while idx < n and (text[idx].isalpha() or text[idx] == "@"):
                    idx += 1
                if idx < n and text[idx] == "*":
                    idx += 1
            elif idx < n:
                idx += 1
            continue

        if opening == "[" and c == "{":
            braces += 1
        elif opening == "[" and c == "}":
            if braces > 0:
                braces -= 1

        if c == opening and (opening != "[" or braces == 0):
            depth += 1
        elif c == closing and (opening != "[" or braces == 0):
            depth -= 1
            if depth == 0:
                return text[body_start:idx], idx + 1

        idx += 1

    return None


def scan_source_lexical(
    text: str,
    rel_path: str,
    pub_id: str,
    ver_id: int,
    *,
    macro_environments: Counter | None = None,
    macro_environment_files: dict | None = None,
) -> tuple[
    Counter[str],  # outer command counts
    defaultdict[str, set[str]],  # outer command files: cmd -> set of rel_paths
    Counter[str],  # macro body command counts
    defaultdict[str, set[str]],  # macro body files: cmd -> set of rel_paths
    Counter[str],  # environment counts
    defaultdict[str, set[str]],  # environment files: env -> set of rel_paths
    list[DefinitionEvidence],  # definition declarations
    dict[str, list[OccurrenceExample]],  # examples <=3 per tag
    list[dict[str, str]],  # warnings / lexical anomalies
]:
    """Deterministically scan TeX source code for commands, environments, and definitions."""
    outer_commands: Counter[str] = Counter()
    outer_cmd_files: defaultdict[str, set[str]] = defaultdict(set)
    macro_commands: Counter[str] = Counter()
    macro_cmd_files: defaultdict[str, set[str]] = defaultdict(set)
    environments: Counter[str] = Counter()
    env_files: defaultdict[str, set[str]] = defaultdict(set)
    definitions: list[DefinitionEvidence] = []
    examples_by_tag: dict[str, list[OccurrenceExample]] = defaultdict(list)
    warnings: list[dict[str, str]] = []

    pos = 0
    n = len(text)
    seen_documentclass = False
    in_document = False
    if macro_environments is None:
        macro_environments = Counter()
    if macro_environment_files is None:
        macro_environment_files = defaultdict(set)

    line_starts = [0]
    for i, c in enumerate(text):
        if c == "\n":
            line_starts.append(i + 1)

    def get_line_number(char_pos: int) -> int:
        import bisect
        return bisect.bisect_right(line_starts, char_pos)

    def get_excerpt(start_pos: int, length: int = 80) -> str:
        snippet = text[start_pos : min(n, start_pos + length)]
        return " ".join(snippet.split())

    def record_example(name: str, target_type: str, scope: str, char_pos: int) -> None:
        if len(examples_by_tag[name]) < 3:
            examples_by_tag[name].append(
                OccurrenceExample(
                    name=name,
                    target_type=target_type,
                    publication=pub_id,
                    version=ver_id,
                    file=rel_path,
                    line=get_line_number(char_pos),
                    source_scope=scope,
                    excerpt=get_excerpt(char_pos, 70),
                    char_offset=char_pos,
                )
            )

    def scan_body_tokens(body: str, def_name: str, body_start_pos: int) -> None:
        """Scan commands inside macro definitions; comments & literals are respected."""
        b_pos = 0
        b_len = len(body)
        while b_pos < b_len:
            b_char = body[b_pos]
            if b_char == "%" and not is_escaped_percent(body, b_pos):
                nl = body.find("\n", b_pos)
                b_pos = b_len if nl == -1 else nl + 1
                continue

            if b_char == "\\":
                s = b_pos
                b_pos += 1
                if b_pos >= b_len:
                    macro_commands["\\"] += 1
                    macro_cmd_files["\\"].add(rel_path)
                    break

                if body[b_pos].isalpha() or body[b_pos] == "@":
                    while b_pos < b_len and (body[b_pos].isalpha() or body[b_pos] == "@"):
                        b_pos += 1
                    if b_pos < b_len and body[b_pos] == "*":
                        b_pos += 1
                    b_cmd = body[s:b_pos]
                else:
                    b_pos += 1
                    b_cmd = body[s:b_pos]

                # Check verb inside body
                if b_cmd in ("\\verb", "\\verb*"):
                    if b_pos < b_len and not body[b_pos].isspace():
                        delim = body[b_pos]
                        b_pos += 1
                        end_delim = body.find(delim, b_pos)
                        if end_delim != -1:
                            b_pos = end_delim + 1
                    continue

                if b_cmd in ("\\begin", "\\end"):
                    group = parse_balanced_group(body, b_pos)
                    if group:
                        env_name, b_pos = group
                        env_name = env_name.strip()
                        if b_cmd == "\\begin":
                            macro_environments[env_name] += 1
                            macro_environment_files.setdefault(env_name, set()).add(rel_path)
                            record_example(env_name, "environment", "macro_body", body_start_pos + s)
                            if env_name in LITERAL_ENVIRONMENTS:
                                closing = "\\end{" + env_name + "}"
                                end = body.find(closing, b_pos)
                                if end < 0:
                                    warnings.append({"file": rel_path, "line": str(get_line_number(body_start_pos + s)),
                                                     "message": "Unclosed macro-body literal: " + env_name})
                                    b_pos = b_len
                                else:
                                    b_pos = end + len(closing)
                        continue

                macro_commands[b_cmd] += 1
                macro_cmd_files[b_cmd].add(rel_path)
                record_example(b_cmd, "command", "macro_body", body_start_pos + s)
                continue

            b_pos += 1

    while pos < n:
        char = text[pos]

        # 1. Comment handling
        if char == "%":
            if not is_escaped_percent(text, pos):
                nl = text.find("\n", pos)
                pos = n if nl == -1 else nl + 1
                continue
            else:
                pos += 1
                continue

        # 2. Command scanning
        if char == "\\":
            cmd_start = pos
            pos += 1
            if pos >= n:
                outer_commands["\\"] += 1
                outer_cmd_files["\\"].add(rel_path)
                break

            if text[pos].isalpha() or text[pos] == "@":
                while pos < n and (text[pos].isalpha() or text[pos] == "@"):
                    pos += 1
                if pos < n and text[pos] == "*":
                    pos += 1
                cmd_name = text[cmd_start:pos]
            else:
                pos += 1
                cmd_name = text[cmd_start:pos]

            if cmd_name == "\\documentclass":
                seen_documentclass = True
            current_scope = ("document_body" if in_document else
                             "preamble" if seen_documentclass else "fragment_or_preamble")

            # Check \begin{env}
            if cmd_name == "\\begin":
                grp = parse_balanced_group(text, pos, "{")
                if grp:
                    env_name, pos = grp
                    env_name = env_name.strip()
                    environments[env_name] += 1
                    env_files[env_name].add(rel_path)
                    record_example(env_name, "environment", current_scope, cmd_start)

                    if env_name == "document":
                        in_document = True

                    # Skip literal environments
                    if env_name in LITERAL_ENVIRONMENTS:
                        closing = f"\\end{{{env_name}}}"
                        end_idx = text.find(closing, pos)
                        if end_idx != -1:
                            pos = end_idx + len(closing)
                        else:
                            warnings.append({
                                "file": rel_path,
                                "line": str(get_line_number(cmd_start)),
                                "message": f"Unclosed literal environment: {env_name}",
                            })
                            pos = n
                        continue
                else:
                    warnings.append({
                        "file": rel_path,
                        "line": str(get_line_number(cmd_start)),
                        "message": "Malformed \\begin missing grouped environment name",
                    })
                continue

            if cmd_name == "\\end":
                grp = parse_balanced_group(text, pos, "{")
                if grp:
                    pos = grp[1]
                continue

            # Check inline \verb
            if cmd_name in ("\\verb", "\\verb*"):
                if pos < n and not text[pos].isspace():
                    delim = text[pos]
                    pos += 1
                    end_delim = text.find(delim, pos)
                    if end_delim != -1:
                        nl_delim = text.find("\n", pos)
                        if nl_delim == -1 or nl_delim > end_delim:
                            pos = end_delim + 1
                    else:
                        warnings.append({
                            "file": rel_path,
                            "line": str(get_line_number(cmd_start)),
                            "message": "Unclosed inline verbatim \\verb delimiter",
                        })
                continue

            # Check newcommand-like declarations
            if cmd_name in (
                "\\newcommand",
                "\\renewcommand",
                "\\providecommand",
                "\\DeclareRobustCommand",
                "\\newcommand*",
                "\\renewcommand*",
                "\\providecommand*",
                "\\DeclareRobustCommand*",
            ):
                cur = skip_whitespace_and_comments(text, pos)
                def_target = ""
                if cur < n and text[cur] == "\\":
                    c_s = cur
                    cur += 1
                    while cur < n and (text[cur].isalpha() or text[cur] == "@"):
                        cur += 1
                    if cur < n and text[cur] == "*":
                        cur += 1
                    def_target = text[c_s:cur]
                else:
                    g = parse_balanced_group(text, cur, "{")
                    if g:
                        def_target = g[0].strip()
                        cur = g[1]

                signature = ""
                sig_arg = parse_balanced_group(text, cur, "[")
                if sig_arg:
                    signature = f"[{sig_arg[0]}]"
                    cur = sig_arg[1]
                    def_val = parse_balanced_group(text, cur, "[")
                    if def_val:
                        signature += f"[{def_val[0]}]"
                        cur = def_val[1]

                body_arg = parse_balanced_group(text, cur, "{")
                if body_arg:
                    body_text, pos = body_arg
                    if def_target:
                        definitions.append(
                            DefinitionEvidence(
                                name=def_target,
                                target_type="command",
                                def_cmd=cmd_name,
                                publication=pub_id,
                                version=ver_id,
                                file=rel_path,
                                line=get_line_number(cmd_start),
                                signature=signature,
                                excerpt=get_excerpt(cmd_start, 70),
                            )
                        )
                    scan_body_tokens(body_text, def_target, pos - len(body_text) - 1)
                else:
                    warnings.append({
                        "file": rel_path,
                        "line": str(get_line_number(cmd_start)),
                        "message": f"Malformed macro definition for {def_target or cmd_name}",
                    })
                continue

            # Check \def, \gdef, \edef, \xdef
            if cmd_name in ("\\def", "\\gdef", "\\edef", "\\xdef"):
                cur = skip_whitespace_and_comments(text, pos)
                def_target = ""
                if cur < n and text[cur] == "\\":
                    c_s = cur
                    cur += 1
                    while cur < n and (text[cur].isalpha() or text[cur] == "@"):
                        cur += 1
                    def_target = text[c_s:cur]

                body_start_brace = text.find("{", cur)
                if body_start_brace != -1:
                    param_text = text[cur:body_start_brace].strip()
                    b_arg = parse_balanced_group(text, body_start_brace, "{")
                    if b_arg:
                        body_text, pos = b_arg
                        if def_target:
                            definitions.append(
                                DefinitionEvidence(
                                    name=def_target,
                                    target_type="command",
                                    def_cmd=cmd_name,
                                    publication=pub_id,
                                    version=ver_id,
                                    file=rel_path,
                                    line=get_line_number(cmd_start),
                                    signature=param_text,
                                    excerpt=get_excerpt(cmd_start, 70),
                                )
                            )
                        scan_body_tokens(body_text, def_target, body_start_brace + 1)
                else:
                    warnings.append({
                        "file": rel_path,
                        "line": str(get_line_number(cmd_start)),
                        "message": f"Malformed primitive \\def without body for {def_target or cmd_name}",
                    })
                continue

            # Check \newenvironment, \renewenvironment
            if cmd_name in (
                "\\newenvironment",
                "\\renewenvironment",
                "\\newenvironment*",
                "\\renewenvironment*",
            ):
                cur = skip_whitespace_and_comments(text, pos)
                env_target_arg = parse_balanced_group(text, cur, "{")
                if env_target_arg:
                    target_env, cur = env_target_arg
                    target_env = target_env.strip()
                    sig_parts = []
                    # Check first optional argument [numargs]
                    s1 = parse_balanced_group(text, cur, "[")
                    if s1:
                        sig_parts.append(f"[{s1[0]}]")
                        cur = s1[1]
                        # Check second optional argument [default]
                        s2 = parse_balanced_group(text, cur, "[")
                        if s2:
                            sig_parts.append(f"[{s2[0]}]")
                            cur = s2[1]

                    b1 = parse_balanced_group(text, cur, "{")
                    if b1:
                        b1_text, cur = b1
                        scan_body_tokens(b1_text, target_env, cur - len(b1_text) - 1)
                        b2 = parse_balanced_group(text, cur, "{")
                        if b2:
                            b2_text, pos = b2
                            scan_body_tokens(b2_text, target_env, pos - len(b2_text) - 1)
                        else:
                            pos = cur
                    else:
                        pos = cur

                    if target_env:
                        definitions.append(
                            DefinitionEvidence(
                                name=target_env,
                                target_type="environment",
                                def_cmd=cmd_name,
                                publication=pub_id,
                                version=ver_id,
                                file=rel_path,
                                line=get_line_number(cmd_start),
                                signature="".join(sig_parts),
                                excerpt=get_excerpt(cmd_start, 70),
                            )
                        )
                continue

            # Check \newtheorem
            if cmd_name in ("\\newtheorem", "\\newtheorem*"):
                cur = skip_whitespace_and_comments(text, pos)
                env_target_arg = parse_balanced_group(text, cur, "{")
                if env_target_arg:
                    target_env, cur = env_target_arg
                    target_env = target_env.strip()
                    # Optional counter [numbered_like]
                    opt1 = parse_balanced_group(text, cur, "[")
                    if opt1:
                        cur = opt1[1]
                    # Required title {Print Title}
                    title_arg = parse_balanced_group(text, cur, "{")
                    if title_arg:
                        title_text, cur = title_arg
                        # Title tokens are scanned into macro_commands, not outer calls
                        scan_body_tokens(title_text, target_env, cur - len(title_text) - 1)
                    # Optional [within]
                    opt2 = parse_balanced_group(text, cur, "[")
                    if opt2:
                        cur = opt2[1]
                    pos = cur

                    definitions.append(
                        DefinitionEvidence(
                            name=target_env,
                            target_type="environment",
                            def_cmd=cmd_name,
                            publication=pub_id,
                            version=ver_id,
                            file=rel_path,
                            line=get_line_number(cmd_start),
                            signature="",
                            excerpt=get_excerpt(cmd_start, 70),
                        )
                    )
                continue

            # Check \DeclareMathOperator
            if cmd_name in ("\\DeclareMathOperator", "\\DeclareMathOperator*"):
                cur = skip_whitespace_and_comments(text, pos)
                op_arg = parse_balanced_group(text, cur, "{")
                if op_arg:
                    target_cmd, cur = op_arg
                    target_cmd = target_cmd.strip()
                    body_op = parse_balanced_group(text, cur, "{")
                    if body_op:
                        pos = body_op[1]
                    else:
                        pos = cur
                    if target_cmd:
                        definitions.append(
                            DefinitionEvidence(
                                name=target_cmd,
                                target_type="command",
                                def_cmd=cmd_name,
                                publication=pub_id,
                                version=ver_id,
                                file=rel_path,
                                line=get_line_number(cmd_start),
                                signature="",
                                excerpt=get_excerpt(cmd_start, 70),
                            )
                        )
                continue

            # Normal outer command
            outer_commands[cmd_name] += 1
            outer_cmd_files[cmd_name].add(rel_path)
            record_example(cmd_name, "command", current_scope, cmd_start)
            continue

        pos += 1

    return (
        outer_commands,
        outer_cmd_files,
        macro_commands,
        macro_cmd_files,
        environments,
        env_files,
        definitions,
        examples_by_tag,
        warnings,
    )


def extract_diagnostic_tag(code: str, message: str, source: str) -> str:
    """Extract exact command name or environment name from engine diagnostic, preserving trailing *."""
    if code == "unhandled_command":
        # Message format: "Command preserved without macro expansion: \foo*"
        m = re.search(r"\\(?:[a-zA-Z@]+\*?|[\s\S])", message)
        if m:
            return m.group(0)
        m = re.search(r"\\(?:[a-zA-Z@]+\*?|[\s\S])", source)
        if m:
            return m.group(0)
        return source[:1] if source.startswith("\\") else "unhandled_command"
    elif code == "unhandled_environment":
        prefix = "Environment has no settled mapping: "
        if message.startswith(prefix):
            return message[len(prefix):]
        if source.startswith("\\begin"):
            group = parse_balanced_group(source, len("\\begin"))
            if group:
                return group[0]
        return "unhandled_environment"
    return code


def display_tag(name: str) -> str:
    """Render control whitespace without breaking Markdown tables."""
    if name == "\\ ":
        return "\\<space>"
    return name.replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t").replace("|", "&#124;")


class LedgerEntries(Mapping):
    """Index checkpoint byte offsets; decode one Version record at a time."""

    def __init__(self, path: Path):
        self.path = path
        self.offsets = {}

    def __len__(self):
        return len(self.offsets)

    def __iter__(self):
        return iter(self.offsets)

    def __contains__(self, key):
        return key in self.offsets

    def __getitem__(self, key):
        with self.path.open("rb") as stream:
            stream.seek(self.offsets[key])
            return json.loads(stream.readline())

    def items(self):
        with self.path.open("rb") as stream:
            for key, offset in self.offsets.items():
                stream.seek(offset)
                yield key, json.loads(stream.readline())


class CorpusAuditor:
    """Orchestrates the two-view inventory across the corpus."""

    def __init__(
        self,
        raw_dir: Path = DEFAULT_RAW_DIR,
        manifest_path: Path = DEFAULT_MANIFEST,
        output_dir: Path = DEFAULT_OUTPUT_DIR,
        mapping_path: Path = DEFAULT_MAPPING,
    ) -> None:
        self.raw_dir = Path(raw_dir).resolve()
        self.manifest_path = Path(manifest_path).resolve()
        self.output_dir = Path(output_dir).resolve()
        self.mapping_path = Path(mapping_path).resolve()

        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.ledger_path = self.output_dir / "ledger.jsonl"
        self.summary_path = self.output_dir / "summary.json"
        self.report_path = self.output_dir / "report.md"
        self.cmd_catalog_json = self.output_dir / "command_catalog.json"
        self.cmd_catalog_csv = self.output_dir / "command_catalog.csv"
        self.env_catalog_json = self.output_dir / "environment_catalog.json"
        self.env_catalog_csv = self.output_dir / "environment_catalog.csv"
        self.fingerprint_path = self.output_dir / "audit_fingerprint.json"

        self.mapping_data = json.loads(self.mapping_path.read_text(encoding="utf-8"))
        self.mapping_sha256 = hashlib.sha256(self.mapping_path.read_bytes()).hexdigest()

        # Compute script sha256 for checkpoint compatibility
        self.script_sha256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()

        # Native SO sha256 if present
        native_so = list(Path(__file__).parent.glob("_hierarchy_native*.so"))
        self.native_sha256 = (
            hashlib.sha256(native_so[0].read_bytes()).hexdigest() if native_so else "not_found"
        )

        self.mapped_commands = set(self.mapping_data.get("commands", {}).keys()) | set(
            self.mapping_data.get("exclusions", {}).get("commands", [])
        )
        self.mapped_environments = set(self.mapping_data.get("environments", {}).keys()) | set(
            self.mapping_data.get("exclusions", {}).get("environments", [])
        )

    def load_manifest(self) -> dict[str, Any]:
        with open(self.manifest_path, encoding="utf-8") as f:
            return json.load(f)

    def check_or_save_fingerprints(self) -> None:
        """Validate checkpoint compatibility; do not resume if mapping or script changed incompatibly."""
        manifest_data = self.manifest_path.read_bytes()
        current_fp = {
            "script_sha256": self.script_sha256,
            "mapping_sha256": self.mapping_sha256,
            "manifest_sha256": hashlib.sha256(manifest_data).hexdigest(),
            "native_sha256": self.native_sha256,
            "pipeline_sha256": hashlib.sha256(b"".join((REPO_ROOT / name).read_bytes() for name in (
                "src/parse/source.py", "src/parse/MultifileGathering/file_tree.py",
                "src/parse/MultifileGathering/merge.py", "src/parse/Hierarchy/engine.py"))).hexdigest(),
        }
        if self.fingerprint_path.exists():
            try:
                saved = json.loads(self.fingerprint_path.read_text(encoding="utf-8"))
                for k in current_fp:
                    if saved.get(k) != current_fp[k]:
                        raise ValueError(
                            f"Fingerprint mismatch on {k}: saved={saved.get(k)}, current={current_fp[k]}. "
                            "Incompatible resume! Clear ledger or use a fresh output directory."
                        )
            except json.JSONDecodeError as error:
                raise ValueError("Invalid fingerprint checkpoint; preserve it and use a fresh output directory") from error
        self.fingerprint_path.write_text(
            json.dumps(current_fp, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def load_ledger_entries(self) -> LedgerEntries:
        """Load latest valid entry for each (publication, version), ignoring incomplete tail lines."""
        latest_entries = LedgerEntries(self.ledger_path)
        if not self.ledger_path.exists():
            return latest_entries

        with self.ledger_path.open("rb") as f:
            valid_end = 0
            while line := f.readline():
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError as error:
                    if f.read().strip():
                        raise ValueError("Corrupt ledger before its final row; cannot resume safely") from error
                    backup = self.output_dir / f"ledger_incomplete_tail_{time.time_ns()}.bin"
                    backup.write_bytes(line)
                    with self.ledger_path.open("r+b") as repair:
                        repair.truncate(valid_end)
                    break
                key = (entry["publication"], entry["version"])
                latest_entries.offsets[key] = valid_end
                valid_end = f.tell()
        return latest_entries

    def audit_version(
        self,
        pub_id: str,
        ver_id: int,
        folder_rel: str,
    ) -> VersionAuditResult:
        """Run two-view audit on a single Version."""
        ver_dir = self.raw_dir / folder_rel
        if not ver_dir.exists():
            ver_dir = self.raw_dir / pub_id / f"v{ver_id}"

        result = VersionAuditResult(publication=pub_id, version=ver_id, status="pending")

        if not ver_dir.is_dir():
            result.status = "no_source"
            result.error = "Directory does not exist"
            return result

        try:
            result.source_signature = compute_dir_signature(ver_dir)
        except OSError as error:
            result.status, result.error = "source_scan_failed", str(error)
            return result

        # Check status.json for download/receipt info
        status_file = ver_dir / "status.json"
        if status_file.is_file():
            try:
                sdata = json.loads(status_file.read_text(encoding="utf-8"))
                result.receipt_kind = sdata.get("kind")
                result.receipt_status = sdata.get("status")
            except (OSError, ValueError) as error:
                result.file_warnings.append({"file": "status.json", "message": str(error)})

        # 1. Lexical scan over all .tex, .sty, .cls files
        all_source_files: list[Path] = []
        tex_files: list[Path] = []
        sty_cls_files: list[Path] = []

        try:
            for p in sorted(ver_dir.rglob("*")):
                if p.is_file():
                    ext = p.suffix.lower()
                    if ext == ".tex":
                        tex_files.append(p)
                        all_source_files.append(p)
                    elif ext in (".sty", ".cls"):
                        sty_cls_files.append(p)
                        all_source_files.append(p)
        except Exception as e:
            result.status = "error"
            result.error = f"Error scanning files: {e}"
            return result

        result.discovered_files = len(all_source_files)
        result.tex_files_count = len(tex_files)
        result.sty_cls_count = len(sty_cls_files)

        all_examples: list[OccurrenceExample] = []

        for sf in all_source_files:
            rel = sf.relative_to(ver_dir).as_posix()
            try:
                if sf.is_symlink() or not sf.resolve().is_relative_to(self.raw_dir):
                    raise OSError("Refusing a symlink or source outside the raw root")
                body, decode_note = read_text_safe(sf)
                if decode_note:
                    result.file_warnings.append({"file": rel, "message": decode_note})
                macro_envs, macro_env_files = Counter(), defaultdict(set)
                (
                    out_cmds,
                    out_files,
                    macro_cmds,
                    macro_files,
                    envs,
                    env_fs,
                    defs,
                    ex_by_tag,
                    file_warns,
                ) = scan_source_lexical(body, rel, pub_id, ver_id,
                    macro_environments=macro_envs, macro_environment_files=macro_env_files)

                result.inspected_files += 1

                for c, cnt in out_cmds.items():
                    result.source_commands[c] = result.source_commands.get(c, 0) + cnt
                    if c not in result.source_commands_files:
                        result.source_commands_files[c] = []
                    result.source_commands_files[c].extend(out_files[c])

                for c, cnt in macro_cmds.items():
                    result.macro_body_commands[c] = result.macro_body_commands.get(c, 0) + cnt
                    if c not in result.macro_body_files:
                        result.macro_body_files[c] = []
                    result.macro_body_files[c].extend(macro_files[c])

                for e, cnt in envs.items():
                    result.source_environments[e] = result.source_environments.get(e, 0) + cnt
                    if e not in result.source_environments_files:
                        result.source_environments_files[e] = []
                    result.source_environments_files[e].extend(env_fs[e])

                for name, count in macro_envs.items():
                    result.macro_body_environments[name] = result.macro_body_environments.get(name, 0) + count
                    files = result.macro_body_environment_files.setdefault(name, [])
                    files.extend(sorted(macro_env_files[name]))
                for d in defs:
                    result.definitions.append(asdict(d))

                for tag_exs in ex_by_tag.values():
                    all_examples.extend(tag_exs)

                result.file_warnings.extend(file_warns)

            except Exception as e:
                result.unreadable_files += 1
                result.file_warnings.append({"file": rel, "message": f"Scan failed: {e}"})

        # Retain <= 3 examples per tag from this Version
        examples_per_tag_ver = defaultdict(list)
        for ex in all_examples:
            if len(examples_per_tag_ver[ex.name]) < 3:
                examples_per_tag_ver[ex.name].append(asdict(ex))
        for tag_ex_list in examples_per_tag_ver.values():
            result.examples.extend(tag_ex_list)

        # Deduplicate file lists inside Version result
        for c in result.source_commands_files:
            result.source_commands_files[c] = sorted(set(result.source_commands_files[c]))
        for c in result.macro_body_files:
            result.macro_body_files[c] = sorted(set(result.macro_body_files[c]))
        for e in result.source_environments_files:
            result.source_environments_files[e] = sorted(set(result.source_environments_files[e]))

        if result.tex_files_count == 0:
            if result.receipt_kind == "pdf":
                result.status = "pdf_non_tex"
            elif result.receipt_status == "empty":
                result.status = "empty_non_tex"
            elif result.receipt_kind in ("download_error", "tar_error") or result.receipt_status == "error":
                result.status = "download_or_unpack_error"
            else:
                result.status = "non_tex"
            return result

        # 2. Reachable pipeline view
        scratch_ft = self.output_dir / ".scratch_ft.json"
        try:
            from src.parse.MultifileGathering.file_tree import build_file_tree
            from src.parse.MultifileGathering.merge import merge_latex
            from src.parse.Hierarchy.engine import HierarchyEngine

            try:
                main_tree = build_file_tree(ver_dir, scratch_ft)
                result.main_file = main_tree.main_file
            except Exception as e:
                result.status = "main_failed"
                result.error = f"build_file_tree error: {e}"
                return result

            try:
                merged_tex = merge_latex(ver_dir, main_file=result.main_file)
                result.merged_bytes = len(merged_tex.encode("utf-8"))
            except Exception as e:
                result.status = "merge_failed"
                result.error = f"merge_latex error: {e}"
                return result

            # Parse with native engine
            arxiv_canon = re.sub(r"^(\d{4})-(\d{4,5})$", r"\1.\2", pub_id)
            engine = HierarchyEngine(arxiv_canon, ver_id, self.mapping_path)
            engine_res = engine.parse(merged_tex)

            # Native offsets refer to UTF-8 bytes, not Python character indexes.
            merged_raw = merged_tex.encode("utf-8")
            diagnostic_example_counts = Counter()
            # Record all diagnostic codes truthfully
            for d in engine_res.diagnostics:
                code = str(d.get("code", "unknown"))
                msg = str(d.get("message", ""))
                src_val = str(d.get("source", ""))
                offset = d.get("offset")
                result.diagnostic_counts[code] = result.diagnostic_counts.get(code, 0) + 1

                tag = extract_diagnostic_tag(code, msg, src_val)
                if code == "unhandled_command":
                    result.unhandled_commands_diag[tag] = result.unhandled_commands_diag.get(tag, 0) + 1
                elif code == "unhandled_environment":
                    result.unhandled_environments_diag[tag] = result.unhandled_environments_diag.get(tag, 0) + 1
                elif code == "unexpanded_definition":
                    result.unexpanded_definitions_diag += 1

                if code not in {"unhandled_command", "unhandled_environment"}:
                    continue
                key = (code, tag)
                if diagnostic_example_counts[key] >= 3:
                    continue
                diagnostic_example_counts[key] += 1
                offset = offset if isinstance(offset, int) else 0
                result.diagnostic_examples.append(asdict(OccurrenceExample(
                    name=tag, target_type="command" if code == "unhandled_command" else "environment",
                    publication=pub_id, version=ver_id, file="<merged>",
                    line=merged_raw[:offset].count(b"\n") + 1, source_scope="<merged>",
                    excerpt=" ".join(merged_raw[offset:offset + 280].decode("utf-8", errors="replace")[:70].split()),
                    byte_offset=offset)))

            if engine_res.complete:
                result.status = "complete"
            else:
                result.status = "partial"

        except Exception as e:
            result.status = "engine_failed"
            result.error = f"HierarchyEngine error: {e}"

        return result

    def run(self, progress_interval: int = 100) -> None:
        """Run audit over the entire manifest with streaming resume."""
        self.check_or_save_fingerprints()
        manifest = self.load_manifest()
        publications = manifest.get("publications", [])
        total_versions = manifest.get("version_count", 0)

        existing_entries = self.load_ledger_entries()
        print(f"Resuming audit: {len(existing_entries)} Versions already verified in ledger.")
        print(f"Total manifest publications: {len(publications)}, total versions: {total_versions}")

        start_time = time.perf_counter()
        processed_count = len(existing_entries)

        ledger_file = open(self.ledger_path, "ab")

        try:
            for pub in publications:
                pub_id = pub["publication"]
                versions = pub.get("versions", [])
                for ver in versions:
                    ver_id = ver["version"]
                    folder_rel = ver.get("folder", f"{pub_id}/v{ver_id}")

                    previous = existing_entries.get((pub_id, ver_id))
                    if previous and previous.get("source_signature") == compute_dir_signature(self.raw_dir / folder_rel):
                        continue

                    res = self.audit_version(pub_id, ver_id, folder_rel)
                    row_offset = ledger_file.tell()
                    ledger_file.write((json.dumps(asdict(res), ensure_ascii=False) + "\n").encode("utf-8"))
                    ledger_file.flush()

                    existing_entries.offsets[(pub_id, ver_id)] = row_offset
                    if previous is None:
                        processed_count += 1

                    if processed_count % progress_interval == 0 or processed_count == total_versions:
                        elapsed = time.perf_counter() - start_time
                        print(
                            f"[{processed_count}/{total_versions}] Audited {pub_id}/v{ver_id} "
                            f"- Status: {res.status} (elapsed: {elapsed:.1f}s)"
                        )

        finally:
            ledger_file.close()

        wall_seconds = time.perf_counter() - start_time
        print(f"Finished {processed_count} versions in {wall_seconds:.1f}s. Aggregating catalogs...")
        self.aggregate_and_report(manifest, wall_seconds)

    def aggregate_and_report(self, manifest: dict[str, Any], wall_seconds: float = 0.0) -> None:
        """Read deduplicated latest entries, aggregate catalogs, and render reports."""
        latest_entries = self.load_ledger_entries()

        status_counts = Counter()
        diagnostics_by_code = Counter()
        publications_seen = set()
        total_source_files = 0
        total_inspected_files = 0
        total_unreadable_files = 0
        total_tex_files = 0
        total_sty_cls_files = 0
        unexpanded_defs_total = 0

        # Command statistics
        cmd_stats: dict[str, dict[str, Any]] = defaultdict(lambda: {
            "source_occurrences": 0,
            "macro_body_occurrences": 0,
            "distinct_pubs": set(),
            "distinct_vers": set(),
            "distinct_files": set(),
            "diagnostic_occurrences": 0,
            "diag_pubs": set(),
            "diag_vers": set(),
            "total_def_declarations": 0,
            "defining_pubs": set(),
            "defining_vers": set(),
            "local_defs": [],
            "examples": [],
            "diagnostic_examples": [],
        })

        # Environment statistics
        env_stats: dict[str, dict[str, Any]] = defaultdict(lambda: {
            "source_occurrences": 0,
            "macro_body_occurrences": 0,
            "distinct_pubs": set(),
            "distinct_vers": set(),
            "distinct_files": set(),
            "diagnostic_occurrences": 0,
            "diag_pubs": set(),
            "diag_vers": set(),
            "total_def_declarations": 0,
            "defining_pubs": set(),
            "defining_vers": set(),
            "local_defs": [],
            "examples": [],
            "diagnostic_examples": [],
        })

        file_ids = {}

        def identify_files(pub, ver, files):
            for file in files:
                key = (pub, ver, file)
                if key not in file_ids:
                    file_ids[key] = len(file_ids)
                yield file_ids[key]

        for (pub, ver), row in latest_entries.items():
            version_key = (pub, ver)
            status = row.get("status", "unknown")
            status_counts[status] += 1
            publications_seen.add(pub)

            total_source_files += row.get("discovered_files", 0)
            total_inspected_files += row.get("inspected_files", 0)
            total_unreadable_files += row.get("unreadable_files", 0)
            total_tex_files += row.get("tex_files_count", 0)
            total_sty_cls_files += row.get("sty_cls_count", 0)
            unexpanded_defs_total += row.get("unexpanded_definitions_diag", 0)

            for code, cnt in row.get("diagnostic_counts", {}).items():
                diagnostics_by_code[code] += cnt

            # Process definitions
            for d in row.get("definitions", []):
                name = d["name"]
                t_type = d.get("target_type", "command")
                st = cmd_stats[name] if t_type == "command" else env_stats[name]
                st["total_def_declarations"] += 1
                st["defining_pubs"].add(pub)
                st["defining_vers"].add(version_key)
                if len(st["local_defs"]) < 3:
                    st["local_defs"].append(d)

            # Process source commands
            for c, count in row.get("source_commands", {}).items():
                st = cmd_stats[c]
                st["source_occurrences"] += count
                st["distinct_pubs"].add(pub)
                st["distinct_vers"].add(version_key)

            for c, files in row.get("source_commands_files", {}).items():
                cmd_stats[c]["distinct_files"].update(identify_files(pub, ver, files))

            for c, count in row.get("macro_body_commands", {}).items():
                st = cmd_stats[c]
                st["macro_body_occurrences"] += count
                st["distinct_pubs"].add(pub)
                st["distinct_vers"].add(version_key)

            for c, files in row.get("macro_body_files", {}).items():
                cmd_stats[c]["distinct_files"].update(identify_files(pub, ver, files))

            # Process source environments
            for e, count in row.get("source_environments", {}).items():
                st = env_stats[e]
                st["source_occurrences"] += count
                st["distinct_pubs"].add(pub)
                st["distinct_vers"].add(version_key)

            for e, files in row.get("source_environments_files", {}).items():
                env_stats[e]["distinct_files"].update(identify_files(pub, ver, files))

            for name, count in row.get("macro_body_environments", {}).items():
                st = env_stats[name]
                st["macro_body_occurrences"] += count
                st["distinct_pubs"].add(pub)
                st["distinct_vers"].add(version_key)
            for name, files in row.get("macro_body_environment_files", {}).items():
                env_stats[name]["distinct_files"].update(identify_files(pub, ver, files))

            # Process diagnostic counts
            for c, count in row.get("unhandled_commands_diag", {}).items():
                st = cmd_stats[c]
                st["diagnostic_occurrences"] += count
                st["diag_pubs"].add(pub)
                st["diag_vers"].add(version_key)

            for e, count in row.get("unhandled_environments_diag", {}).items():
                st = env_stats[e]
                st["diagnostic_occurrences"] += count
                st["diag_pubs"].add(pub)
                st["diag_vers"].add(version_key)

            # Store examples directly by tag
            for ex in row.get("examples", []):
                t_name = ex.get("name")
                t_type = ex.get("target_type", "command")
                if t_name:
                    st = cmd_stats[t_name] if t_type == "command" else env_stats[t_name]
                    if len(st["examples"]) < 3:
                        st["examples"].append(ex)

            for dex in row.get("diagnostic_examples", []):
                t_name = dex.get("name")
                t_type = dex.get("target_type", "command")
                if t_name:
                    st = cmd_stats[t_name] if t_type == "command" else env_stats[t_name]
                    if len(st["diagnostic_examples"]) < 3:
                        st["diagnostic_examples"].append(dex)

        # Build command catalog
        cmd_catalog: list[dict[str, Any]] = []
        for name, st in cmd_stats.items():
            is_mapped = name in self.mapped_commands or name in CORE_RUNTIME_HANDLED
            # Only catalog unmapped tags or tags that caused diagnostics
            if is_mapped and st["diagnostic_occurrences"] == 0:
                continue

            num_pubs = len(st["distinct_pubs"])
            num_def_pubs = len(st["defining_pubs"])

            if is_mapped:
                cat = "mapped_or_builtin"
                rec = "none"
            elif st["distinct_vers"] and st["distinct_vers"].issubset(st["defining_vers"]):
                cat = "locally_defined_in_all_sources"
                rec = "definition_resolver"
            elif num_def_pubs > 0:
                cat = "locally_defined_in_some_sources"
                rec = "definition_resolver_or_manual_review"
            else:
                cat = "unmapped_in_parser"
                rec = SAFE_ACTION_HEURISTICS.get(name, "manual_review")

            cmd_catalog.append({
                "name": name,
                "type": "command",
                "classification": cat,
                "recommended_action": rec,
                "source_occurrences": st["source_occurrences"],
                "macro_body_occurrences": st["macro_body_occurrences"],
                "distinct_publications": num_pubs,
                "distinct_versions": len(st["distinct_vers"]),
                "distinct_files": len(st["distinct_files"]),
                "diagnostic_occurrences": st["diagnostic_occurrences"],
                "diagnostic_publications": len(st["diag_pubs"]),
                "diagnostic_versions": len(st["diag_vers"]),
                "total_definition_declarations": st["total_def_declarations"],
                "defining_publications": num_def_pubs,
                "defining_versions": len(st["defining_vers"]),
                "definition_evidence": st["local_defs"][:3],
                "examples": st["examples"][:3],
                "diagnostic_examples": st["diagnostic_examples"][:3],
            })

        cmd_catalog.sort(
            key=lambda x: (
                -x["distinct_publications"],
                -x["source_occurrences"],
                x["name"],
            )
        )

        # Build environment catalog
        env_catalog: list[dict[str, Any]] = []
        for name, st in env_stats.items():
            is_mapped = name in self.mapped_environments
            if is_mapped and st["diagnostic_occurrences"] == 0:
                continue

            num_pubs = len(st["distinct_pubs"])
            num_def_pubs = len(st["defining_pubs"])

            if is_mapped:
                cat = "mapped_or_builtin"
                rec = "none"
            elif st["distinct_vers"] and st["distinct_vers"].issubset(st["defining_vers"]):
                cat = "locally_defined_in_all_sources"
                rec = "definition_resolver"
            elif num_def_pubs > 0:
                cat = "locally_defined_in_some_sources"
                rec = "definition_resolver_or_manual_review"
            else:
                cat = "unmapped_in_parser"
                rec = SAFE_ENV_HEURISTICS.get(name, "manual_review")

            env_catalog.append({
                "name": name,
                "type": "environment",
                "classification": cat,
                "recommended_action": rec,
                "source_occurrences": st["source_occurrences"],
                "macro_body_occurrences": st["macro_body_occurrences"],
                "distinct_publications": num_pubs,
                "distinct_versions": len(st["distinct_vers"]),
                "distinct_files": len(st["distinct_files"]),
                "diagnostic_occurrences": st["diagnostic_occurrences"],
                "diagnostic_publications": len(st["diag_pubs"]),
                "diagnostic_versions": len(st["diag_vers"]),
                "total_definition_declarations": st["total_def_declarations"],
                "defining_publications": num_def_pubs,
                "defining_versions": len(st["defining_vers"]),
                "definition_evidence": st["local_defs"][:3],
                "examples": st["examples"][:3],
                "diagnostic_examples": st["diagnostic_examples"][:3],
            })

        env_catalog.sort(
            key=lambda x: (
                -x["distinct_publications"],
                -x["source_occurrences"],
                x["name"],
            )
        )

        # Write JSON catalogs
        self.cmd_catalog_json.write_text(
            json.dumps(cmd_catalog, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        self.env_catalog_json.write_text(
            json.dumps(env_catalog, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        # Write CSV catalogs
        self._write_catalog_csv(self.cmd_catalog_csv, cmd_catalog)
        self._write_catalog_csv(self.env_catalog_csv, env_catalog)

        # Account for Publications without versions
        manifest_pubs = manifest.get("publications", [])
        no_version_pubs = [
            p["publication"] for p in manifest_pubs if not p.get("versions")
        ]

        summary = {
            "scope": manifest.get("scope", "All Publications"),
            "fingerprints": {
                "script_sha256": self.script_sha256,
                "mapping_sha256": self.mapping_sha256,
                "manifest_sha256": hashlib.sha256(self.manifest_path.read_bytes()).hexdigest(),
                "native_sha256": self.native_sha256,
            },
            "manifest_publications": manifest.get(
                "publication_count", len(manifest_pubs)
            ),
            "manifest_versions": manifest.get("version_count", 0),
            "no_version_publications_count": len(no_version_pubs),
            "no_version_publications": no_version_pubs,
            "inspected_publications": len(publications_seen),
            "inspected_versions": sum(status_counts.values()),
            "status_breakdown": dict(status_counts),
            "diagnostics_by_code": dict(diagnostics_by_code),
            "total_source_files_discovered": total_source_files,
            "total_source_files_inspected": total_inspected_files,
            "total_source_files_unreadable": total_unreadable_files,
            "tex_files_inspected": total_tex_files,
            "sty_cls_files_inspected": total_sty_cls_files,
            "unsupported_commands_count": len(cmd_catalog),
            "unsupported_environments_count": len(env_catalog),
            "unexpanded_definitions_diagnostic_total": unexpanded_defs_total,
            "wall_seconds": wall_seconds,
        }
        self.summary_path.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        self._render_report_md(summary, cmd_catalog, env_catalog)

    def _write_catalog_csv(self, path: Path, catalog: list[dict[str, Any]]) -> None:
        fieldnames = [
            "name",
            "type",
            "classification",
            "recommended_action",
            "source_occurrences",
            "macro_body_occurrences",
            "distinct_publications",
            "distinct_versions",
            "distinct_files",
            "diagnostic_occurrences",
            "diagnostic_publications",
            "diagnostic_versions",
            "total_definition_declarations",
            "defining_publications",
            "defining_versions",
        ]
        with open(path, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            for row in catalog:
                writer.writerow(row)

    def _render_report_md(
        self,
        summary: dict[str, Any],
        cmd_catalog: list[dict[str, Any]],
        env_catalog: list[dict[str, Any]],
    ) -> None:
        lines = [
            "# Unsupported LaTeX Commands & Environments Inventory Report",
            "",
            "## 1. Corpus Coverage",
            "",
            f"- **Manifest Publications**: {summary['manifest_publications']}",
            f"- **Manifest Versions**: {summary['manifest_versions']}",
            f"- **No-Version Publications**: {summary['no_version_publications_count']}",
            f"- **Inspected Publications**: {summary['inspected_publications']}",
            f"- **Inspected Versions**: {summary['inspected_versions']}",
            f"- **Source Files**: {summary['total_source_files_discovered']} discovered, "
            f"{summary['total_source_files_inspected']} inspected, "
            f"{summary['total_source_files_unreadable']} unreadable "
            f"({summary['tex_files_inspected']} .tex, {summary['sty_cls_files_inspected']} .sty/.cls)",
            f"- **Wall Seconds**: {summary['wall_seconds']:.1f}s",
            "",
            "### Fingerprints",
            f"- Mapping SHA-256: `{summary['fingerprints']['mapping_sha256']}`",
            f"- Script SHA-256: `{summary['fingerprints']['script_sha256']}`",
            f"- Manifest SHA-256: `{summary['fingerprints']['manifest_sha256']}`",
            "",
            "### Version Status Breakdown",
            "",
            "| Status | Versions | Description |",
            "|---|---:|---|",
        ]
        for st, count in sorted(summary["status_breakdown"].items()):
            lines.append(f"| `{st}` | {count} | |")

        lines.extend([
            "",
            "### Diagnostics by Code",
            "",
            "| Code | Count |",
            "|---|---:|",
        ])
        for code, count in sorted(summary["diagnostics_by_code"].items()):
            lines.append(f"| `{code}` | {count} |")

        lines.extend([
            "",
            "## 2. Top Unsupported Commands (by Distinct Publications Affected)",
            "",
            "| Command | Source Count | Distinct Pubs | Distinct Vers | Distinct Files | Diag Count | Classification | Recommended Action |",
            "|---|---:|---:|---:|---:|---:|---|---|",
        ])
        for c in cmd_catalog[:30]:
            lines.append(
                f"| `{display_tag(c['name'])}` | {c['source_occurrences']} | {c['distinct_publications']} | "
                f"{c['distinct_versions']} | {c['distinct_files']} | {c['diagnostic_occurrences']} | "
                f"{c['classification']} | `{c['recommended_action']}` |"
            )

        lines.extend([
            "",
            "## 3. Top Unsupported Environments",
            "",
            "| Environment | Source Count | Distinct Pubs | Distinct Vers | Distinct Files | Diag Count | Classification | Recommended Action |",
            "|---|---:|---:|---:|---:|---:|---|---|",
        ])
        for e in env_catalog[:20]:
            lines.append(
                f"| `{display_tag(e['name'])}` | {e['source_occurrences']} | {e['distinct_publications']} | "
                f"{e['distinct_versions']} | {e['distinct_files']} | {e['diagnostic_occurrences']} | "
                f"{e['classification']} | `{e['recommended_action']}` |"
            )

        lines.extend([
            "",
            "## 4. Artifact Links",
            "",
            "- Command Catalog: [JSON](command_catalog.json) · [CSV](command_catalog.csv)",
            "- Environment Catalog: [JSON](environment_catalog.json) · [CSV](environment_catalog.csv)",
            "- Per-Version Ledger: [ledger.jsonl](ledger.jsonl)",
            "- Machine Summary: [summary.json](summary.json)",
            "- Fingerprint: [audit_fingerprint.json](audit_fingerprint.json)",
            "",
            "## 5. Engineering Limitations & Methodology Notes",
            "",
            "- **Two-view distinction**: Lexical presence in source files does not imply compilation reached that branch (e.g., dead branches, custom macros, preambles, or unmerged files).",
            "- **Native engine diagnostics**: Only captures reachable commands in successful merges; merge failures are tracked in the ledger and covered by the source-wide view.",
            "- **Locally defined macros**: Definitions are cataloged with bounded excerpts; names absent from mapping are not automatically undefined in TeX.",
            "- **Recommendations**: Action values are advisory hints for human review and should not be used as automated modifications to mapping.json.",
            "",
        ])

        self.report_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", type=Path, default=DEFAULT_RAW_DIR)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--mapping", type=Path, default=DEFAULT_MAPPING)
    parser.add_argument("--progress", type=int, default=100)
    args = parser.parse_args()

    auditor = CorpusAuditor(
        raw_dir=args.raw_dir,
        manifest_path=args.manifest,
        output_dir=args.output_dir,
        mapping_path=args.mapping,
    )
    auditor.run(progress_interval=args.progress)


if __name__ == "__main__":
    main()
