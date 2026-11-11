"""Deterministic conversion from StructureTree blocks to LeafTree nodes."""

from __future__ import annotations

import re

from .sentences import sentence_spans
from .types import (
    Block,
    Leaf,
    LeafTree,
    ListNode,
    Section,
    StructureTree,
    validate_B,
)

LEAVES_VERSION = "1"

LIST_ENVS = {"itemize", "enumerate", "description"}
FIGURE_ENVS = {"figure", "figure*", "table", "table*"}
MATH_ENVS = {
    "equation", "equation*", "align", "align*", "gather", "gather*",
    "multline", "multline*", "flalign", "flalign*", "displaymath",
}

SPECIAL_RE = re.compile(
    r"\\begin\s*\{(?P<env>"
    r"itemize|enumerate|description|"
    r"figure\*?|table\*?|"
    r"equation\*?|align\*?|gather\*?|"
    r"multline\*?|flalign\*?|displaymath"
    r")\}|(?P<delimiter>\\\[|\$\$)"
)

LIST_TOKEN_RE = re.compile(
    r"\\begin\s*\{(?:itemize|enumerate|description)\}"
    r"|\\end\s*\{(?:itemize|enumerate|description)\}"
    r"|\\item\b"
)


def _find_environment_end(
    text: str,
    start: int,
    env: str,
) -> tuple[int, int] | None:
    """Find the matching end of a possibly nested LaTeX environment."""
    pattern = re.compile(
        r"\\(begin|end)\s*\{" + re.escape(env) + r"\}"
    )

    depth = 0

    for match in pattern.finditer(text, start):
        if match.group(1) == "begin":
            depth += 1
        else:
            depth -= 1

            if depth == 0:
                return match.start(), match.end()

    return None


def _append_sentences(
    output: list,
    text: str,
    base: int,
) -> None:
    """Append sentence leaves while preserving absolute source offsets."""
    for start, end in sentence_spans(text):
        output.append(
            Leaf(
                kind="sentence",
                raw=text[start:end],
                span=(base + start, base + end),
            )
        )


def _item_content_start(text: str, position: int) -> int:
    """Skip the optional label following a LaTeX item command."""
    i = position

    while i < len(text) and text[i].isspace():
        i += 1

    if i < len(text) and text[i] == "[":
        end = text.find("]", i + 1)

        if end >= 0:
            i = end + 1

    while i < len(text) and text[i].isspace():
        i += 1

    return i


def _parse_list(
    text: str,
    start: int,
    base: int,
    env: str,
) -> ListNode | None:
    """Convert itemize/enumerate/description into itemize -> item."""
    begin = re.match(
        r"\\begin\s*\{" + re.escape(env) + r"\}",
        text[start:],
    )

    if begin is None:
        return None

    matching_end = _find_environment_end(text, start, env)

    if matching_end is None:
        return None

    end_start, end_end = matching_end
    content_start = start + begin.end()

    markers = []
    nested_depth = 0

    for match in LIST_TOKEN_RE.finditer(
        text, content_start, end_start
    ):
        token = match.group()

        if token.startswith(r"\begin"):
            nested_depth += 1

        elif token.startswith(r"\end"):
            nested_depth = max(0, nested_depth - 1)

        elif nested_depth == 0:
            markers.append(match)

    items = []

    for index, marker in enumerate(markers):
        segment_end = (
            markers[index + 1].start()
            if index + 1 < len(markers)
            else end_start
        )

        content_start_item = _item_content_start(
            text, marker.end()
        )

        children = _parse_content(
            text[content_start_item:segment_end],
            base + content_start_item,
        )

        if children:
            items.append(
                ListNode(
                    kind="item",
                    span=(
                        base + marker.start(),
                        base + segment_end,
                    ),
                    children=children,
                )
            )

    return ListNode(
        kind="itemize",
        span=(base + start, base + end_end),
        children=items,
    )


def _parse_content(text: str, base: int) -> list:
    """Parse text and embedded display structures into ordered leaves."""
    output = []
    cursor = 0

    while cursor < len(text):
        match = SPECIAL_RE.search(text, cursor)

        if match is None:
            _append_sentences(
                output,
                text[cursor:],
                base + cursor,
            )
            break

        _append_sentences(
            output,
            text[cursor:match.start()],
            base + cursor,
        )

        env = match.group("env")
        delimiter = match.group("delimiter")

        if delimiter:
            closing = r"\]" if delimiter == r"\[" else "$$"
            close_start = text.find(closing, match.end())

            if close_start < 0:
                _append_sentences(
                    output,
                    text[match.start():],
                    base + match.start(),
                )
                break

            end = close_start + len(closing)

            output.append(
                Leaf(
                    kind="formula",
                    raw=text[match.start():end],
                    span=(
                        base + match.start(),
                        base + end,
                    ),
                )
            )

            cursor = end
            continue

        matching_end = _find_environment_end(
            text, match.start(), env
        )

        if matching_end is None:
            _append_sentences(
                output,
                text[match.start():],
                base + match.start(),
            )
            break

        _, end = matching_end
        raw = text[match.start():end]
        span = (
            base + match.start(),
            base + end,
        )

        if env in LIST_ENVS:
            node = _parse_list(
                text, match.start(), base, env
            )

            if node is not None:
                output.append(node)

        elif env in FIGURE_ENVS:
            output.append(
                Leaf(
                    kind="figure",
                    raw=raw,
                    span=span,
                )
            )

        elif env in MATH_ENVS:
            output.append(
                Leaf(
                    kind="formula",
                    raw=raw,
                    span=span,
                )
            )

        cursor = end

    return output


def _convert_block(block: Block) -> list:
    """Convert one input Block into Leaf/ListNode objects."""
    if block.type == "display_math":
        return [
            Leaf(
                kind="formula",
                raw=block.raw,
                span=block.span,
            )
        ]

    if block.type == "text":
        return _parse_content(
            block.raw,
            block.span[0],
        )

    if block.type == "env":
        env = block.env

        if env in LIST_ENVS:
            node = _parse_list(
                block.raw, 0, block.span[0], env
            )
            return [node] if node is not None else [
                Leaf("sentence", block.raw, block.span)
            ]

        if env in FIGURE_ENVS:
            return [
                Leaf("figure", block.raw, block.span)
            ]

        if env in MATH_ENVS:
            return [
                Leaf("formula", block.raw, block.span)
            ]

        # Unsupported environments are preserved as one leaf.
        return [
            Leaf("sentence", block.raw, block.span)
        ]

    raise ValueError(f"Unsupported Block type: {block.type!r}")


def _convert_section(section: Section) -> Section:
    """Recursively preserve section hierarchy and convert its blocks."""
    children = []

    for child in section.children:
        if isinstance(child, Section):
            children.append(_convert_section(child))

        elif isinstance(child, Block):
            children.extend(_convert_block(child))

        else:
            raise TypeError(
                f"Unexpected input node: {type(child).__name__}"
            )

    return Section(
        kind=section.kind,
        title_raw=section.title_raw,
        starred=section.starred,
        span=section.span,
        children=children,
    )


def build_leaves(tree: StructureTree) -> LeafTree:
    """Build a LeafTree from a validated StructureTree."""
    errors = validate_B(tree, raise_on_error=False)

    if errors:
        raise ValueError(
            "Invalid StructureTree:\n" + "\n".join(errors)
        )

    result = LeafTree(
        arxiv_id=tree.arxiv_id,
        version=tree.version,
        root=_convert_section(tree.root),
        dropped=list(tree.dropped),
        issues=list(tree.issues),
        leaves_version=LEAVES_VERSION,
    )

    return result


__all__ = ["LEAVES_VERSION", "build_leaves"]
