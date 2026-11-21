
"""Deterministic sentence splitting for LaTeX text blocks."""

from __future__ import annotations

import re


SENTENCE_SPLITTER_VERSION = "1"

ABBREVIATIONS = (
    "i.e.",
    "e.g.",
    "et al.",
    "etc.",
    "Fig.",
    "Eq.",
    "Sec.",
    "Tab.",
    "vs.",
    "cf.",
)

_ABBREVIATION_RE = re.compile(
    r"\b(?:i\.e|e\.g|et\s+al|etc|fig|eq|sec|tab|vs|cf)\.",
    re.IGNORECASE,
)

_URL_RE = re.compile(r"https?://[^\s<>{}\[\]]+")

_CLOSING_CHARS = "\"'”’)]}"


def _is_escaped(text: str, index: int) -> bool:
    """Return True if a character is preceded by an odd number of backslashes."""
    count = 0
    index -= 1

    while index >= 0 and text[index] == "\\":
        count += 1
        index -= 1

    return count % 2 == 1


def _mark(mask: list[bool], start: int, end: int) -> None:
    """Mark a half-open range as protected."""
    for index in range(start, end):
        mask[index] = True


def _find_unescaped(text: str, token: str, start: int) -> int:
    """Find the next unescaped occurrence of token."""
    index = start

    while True:
        index = text.find(token, index)

        if index < 0:
            return -1

        if not _is_escaped(text, index):
            return index

        index += len(token)


def _protect_math(text: str, mask: list[bool]) -> None:
    """Protect inline and display math regions."""
    n = len(text)
    i = 0

    while i < n:
        if text.startswith(r"\(", i):
            end = _find_unescaped(text, r"\)", i + 2)
            if end >= 0:
                _mark(mask, i, end + 2)
                i = end + 2
                continue

        if text.startswith(r"\[", i):
            end = _find_unescaped(text, r"\]", i + 2)
            if end >= 0:
                _mark(mask, i, end + 2)
                i = end + 2
                continue

        if text.startswith("$$", i) and not _is_escaped(text, i):
            end = _find_unescaped(text, "$$", i + 2)
            if end >= 0:
                _mark(mask, i, end + 2)
                i = end + 2
                continue

        if text[i] == "$" and not _is_escaped(text, i):
            if i + 1 < n and text[i + 1] == "$":
                i += 2
                continue

            end = _find_unescaped(text, "$", i + 1)
            if end >= 0:
                _mark(mask, i, end + 1)
                i = end + 1
                continue

        i += 1


def _protect_brace_groups(text: str, mask: list[bool]) -> None:
    """Protect balanced command arguments, including nested braces."""
    stack: list[int] = []

    for i, char in enumerate(text):
        if _is_escaped(text, i):
            continue

        if char == "{":
            stack.append(i)

        elif char == "}" and stack:
            start = stack.pop()
            if not stack:
                _mark(mask, start, i + 1)


def _protect_urls(text: str, mask: list[bool]) -> None:
    """Protect URLs without consuming sentence-ending punctuation."""
    for match in _URL_RE.finditer(text):
        start, end = match.span()
        value = match.group()

        while value and value[-1] in ".,!?;:":
            value = value[:-1]
            end -= 1

        if value:
            _mark(mask, start, end)


def _protect_abbreviations(text: str, mask: list[bool]) -> None:
    """Protect common abbreviations from sentence splitting."""
    for match in _ABBREVIATION_RE.finditer(text):
        _mark(mask, match.start(), match.end())


def _build_protection_mask(text: str) -> list[bool]:
    """Build a character-level mask for protected regions."""
    mask = [False] * len(text)

    _protect_math(text, mask)
    for match in re.finditer(
        r'\\\\begin\s*\{math\}.*?\\\\end\s*\{math\}',
        text,
        re.DOTALL,
    ):
        _mark(mask, match.start(), match.end())
    _protect_brace_groups(text, mask)
    _protect_urls(text, mask)
    _protect_abbreviations(text, mask)

    # Decimal points must not be treated as sentence boundaries.
    for i in range(1, len(text) - 1):
        if (
            text[i] == "."
            and text[i - 1].isdigit()
            and text[i + 1].isdigit()
        ):
            mask[i] = True

    return mask


def sentence_spans(text: str) -> list[tuple[int, int]]:
    """
    Return sentence spans as half-open character offsets.

    Whitespace between sentences is excluded from spans.
    Original text is never modified.
    """
    if not text or not text.strip():
        return []

    mask = _build_protection_mask(text)

    spans: list[tuple[int, int]] = []
    start = 0
    i = 0
    n = len(text)

    while i < n:
        if mask[i] or text[i] not in ".?!":
            i += 1
            continue

        end = i + 1

        # Keep closing quotation marks and brackets with the sentence.
        while end < n and text[end] in _CLOSING_CHARS:
            end += 1

        # A punctuation mark is a boundary only before whitespace or EOF.
        if end == n or text[end].isspace():
            left = start
            right = end

            while left < right and text[left].isspace():
                left += 1

            while right > left and text[right - 1].isspace():
                right -= 1

            if left < right:
                spans.append((left, right))

            start = end

            while start < n and text[start].isspace():
                start += 1

            i = start
            continue

        i += 1

    # Preserve the final sentence even without punctuation.
    left = start
    right = n

    while left < right and text[left].isspace():
        left += 1

    while right > left and text[right - 1].isspace():
        right -= 1

    if left < right:
        spans.append((left, right))

    return spans


def split_sentences(text: str) -> list[str]:
    """Split text into sentences while preserving original sentence content."""
    return [
        text[start:end]
        for start, end in sentence_spans(text)
    ]
