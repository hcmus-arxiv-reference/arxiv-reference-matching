"""Normalize one LaTeX Element under the M2.4a contract in docs/m2-interfaces.md."""
from __future__ import annotations

import re

from .source import _control

NORMALIZE_VERSION = "1"

# Course M2 cleanup and the group's M2.4a examples. The value is the argument
# to discard along with the formatting command (if present for optional rules).
# https://hcmus-cs-ta.github.io/lab-book/intro-ds/statement/parsing/
_FORMATTING = dict.fromkeys(
    ("centering", "small", "footnotesize", "scriptsize", "tiny", "large", "Large",
     "LARGE", "huge", "Huge", "noindent", "hline"), "none"
)
_FORMATTING.update(dict.fromkeys(("toprule", "midrule", "bottomrule"), "optional"))
_FORMATTING.update(dict.fromkeys(("vspace", "hspace"), "required"))
_ENV = re.compile(r"\\(begin|end)\s*\{([A-Za-z]+\*?)\}")
_DISPLAY = re.compile(r"\\begin\{(equation\*?|displaymath|align\*?|gather\*?)\}(.*)\\end\{\1\}", re.S)
_LITERALS = {"verbatim", "verbatim*", "Verbatim", "lstlisting", "minted"}
_FLOATS = {"figure", "figure*", "table", "table*"}
_PLACEMENT = re.compile(r"[!htbpH]+")
_PROTECTED = re.compile(r"(?:[A-Za-z]*cite[A-Za-z]*|url|path|href|label|includegraphics)", re.I)


def _space_end(text: str, pos: int) -> int:
    while pos < len(text) and text[pos].isspace():
        pos += 1
    return pos


def _group_end(text: str, pos: int, opening: str) -> int | None:
    """Find a balanced argument without interpreting or rewriting its contents."""
    pos = _space_end(text, pos)
    if pos == len(text) or text[pos] != opening:
        return None
    stack = ["}" if opening == "{" else "]"]
    pos += 1
    while pos < len(text):
        char = text[pos]
        if char == "\\":
            _, pos = _control(text, pos)
            continue
        if char == "{" or (char == "[" and stack[-1] == "]"):
            stack.append("}" if char == "{" else "]")
        elif char == stack[-1]:
            stack.pop()
            if not stack:
                return pos + 1
        pos += 1
    return None


def _command_argument_end(text: str, end: int) -> int:
    if text[end:end + 1] == "*":
        end += 1
    while (optional := _group_end(text, end, "[")) is not None:
        end = optional
    return _group_end(text, end, "{") or end


def _comment_end(text: str, pos: int) -> int:
    end = text.find("\n", pos)
    if end < 0:
        return len(text)
    end += 1
    while text[end:end + 1] in (" ", "\t"):
        end += 1
    return end


def _inline_end(text: str, pos: int, closing: str) -> tuple[int, int] | None:
    while pos < len(text):
        if closing == r"\end{math}" and (env := _ENV.match(text, pos)) and env.groups() == ("end", "math"):
            return pos, env.end()
        if text.startswith(closing, pos):
            if closing == "$" and text.startswith("$$", pos):
                return None
            return pos, pos + len(closing)
        if text[pos] == "%":
            pos = _comment_end(text, pos)
        elif text[pos] == "\\":
            _, pos = _control(text, pos)
        else:
            pos += 1
    return None


def _compact(text: str, *, floats: bool = False, inline: bool = True) -> str:
    parts: list[str] = []
    pos = 0
    while pos < len(text):
        char = text[pos]
        if char.isspace():
            if parts and parts[-1] != " ":
                parts.append(" ")
            pos = _space_end(text, pos)
            continue
        if char == "%":
            pos = _comment_end(text, pos)
            continue
        if (char.isalpha() or char == "@") and parts and re.fullmatch(r"\\[\w@]+", parts[-1]):
            # Removing a command or comment must not join a control word to
            # following letters, e.g. \alpha\hspace{1em}x into \alphax.
            parts.append(" ")
        if text.startswith("$$", pos):
            parts.append("$$")
            pos += 2
            continue

        end = pos + 1
        closing = "$" if inline and char == "$" else None
        if char == "\\":
            command, end = _control(text, pos)
            if command in ("verb", "lstinline"):
                start = end + int(text[end:end + 1] == "*")
                if command == "lstinline":
                    start = _group_end(text, start, "[") or start
                if start < len(text) and not text[start].isspace():
                    stop = text.find(text[start], start + 1)
                    end = len(text) if stop < 0 else stop + 1
                parts.append(text[pos:end])
                pos = end
                continue
            if command in ("begin", "end") and (env := _ENV.match(text, pos)):
                action, name = env.groups()
                end = env.end()
                if action == "begin" and name in _LITERALS:
                    token = "\\end{" + name + "}"
                    stop = text.find(token, end)
                    end = len(text) if stop < 0 else stop + len(token)
                    parts.append(text[pos:end])
                    pos = end
                    continue
                if inline and action == "begin" and name == "math":
                    closing = r"\end{math}"
                else:
                    if floats and action == "begin" and name in _FLOATS:
                        option = _group_end(text, end, "[")
                        if option is not None and _PLACEMENT.fullmatch(text[_space_end(text, end) + 1:option - 1].strip()):
                            end = option
                    parts.append("\\" + action + "{" + name + "}")
                    pos = end
                    continue
            elif command in _FORMATTING:
                argument = _FORMATTING[command]
                start = end + int(argument == "required" and text[end:end + 1] == "*")
                stop = _group_end(text, start, "{" if argument == "required" else "[") if argument != "none" else None
                if stop is not None or argument != "required":
                    pos = stop or end
                    continue
            elif _PROTECTED.fullmatch(command):
                end = _command_argument_end(text, end)
            elif inline and command == "(":
                closing = r"\)"

        if closing and (pair := _inline_end(text, end, closing)):
            start_close, end_close = pair
            body = _compact(text[end:start_close], inline=False)
            # Retain empty math delimiters to avoid turning them into $$.
            parts.append(f"${body}$" if body else text[pos:end_close])
            pos = end_close
        else:
            parts.append(text[pos:end])
            pos = end
    if parts and parts[-1] == " ":
        parts.pop()
    return "".join(parts)


def normalize(kind: str, raw: str) -> str:
    """Return canonical content while keeping labels, citation keys and math tokens.

    One formula input stays one Element. Aligned/gathered lines retain their
    separators inside the canonical equation wrapper. This function does not
    decide where the upstream parser splits a multi-line display.
    """
    clean = _compact(raw, floats=kind == "figure", inline=kind != "formula")
    if kind != "formula" or not clean:
        return clean
    display = _DISPLAY.fullmatch(clean)
    if display:
        name, body = display.groups()
        body = body.strip()
        nested = {"align": "aligned", "gather": "gathered"}.get(name.rstrip("*"))
        if nested:
            body = "\\begin{" + nested + "}" + body + "\\end{" + nested + "}"
    elif (clean.startswith("$$") and clean.endswith("$$")) or (
        clean.startswith(r"\[") and clean.endswith(r"\]")
    ):
        body = clean[2:-2].strip()
    else:
        body = clean
    return r"\begin{equation}" + body + r"\end{equation}"
