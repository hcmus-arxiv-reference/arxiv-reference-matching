"""Deterministic conversion from StructureTree blocks to LeafTree nodes."""

from __future__ import annotations

import re

from .leaf_markup import LIST_ENVS, PROSE_ENVS, label_end
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

FIGURE_ENVS = {"figure", "figure*", "table", "table*"}
MATH_ENVS = {
    "equation", "equation*", "align", "align*", "gather", "gather*",
    "multline", "multline*", "flalign", "flalign*", "displaymath",
    "eqnarray", "eqnarray*", "alignat", "alignat*",
}

SPECIAL_RE = re.compile(
    r"\\begin\s*\{(?P<env>"
    + "|".join(re.escape(name) for name in sorted(
        LIST_ENVS | FIGURE_ENVS | MATH_ENVS | PROSE_ENVS
    ))
    + r")\}|(?P<delimiter>\\\[|\$\$)"
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

        content_start_item = marker.end()
        while content_start_item < segment_end and text[content_start_item].isspace():
            content_start_item += 1
        end_label = label_end(text, content_start_item)
        children = []
        if content_start_item < end_label <= segment_end:
            children.append(Leaf(
                "sentence", text[content_start_item:end_label],
                (base + content_start_item, base + end_label),
            ))
            content_start_item = end_label
        children.extend(_parse_content(
            text[content_start_item:segment_end], base + content_start_item
        ))

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

    # Preserve the raw text of a block wholly enclosed in a simple \iffalse.
    if text.lstrip().startswith(r"\iffalse") and re.fullmatch(
        r"\s*\\iffalse(?![A-Za-z])(?:(?!\\(?:if[A-Za-z]*|else|fi)(?![A-Za-z])).)*"
        r"\\fi(?![A-Za-z])\s*",
        text,
        flags=re.DOTALL,
    ):
        _append_sentences(output, text, base)
        return output
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

        close_start, end = matching_end
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

        elif env in PROSE_ENVS:
            content_start = match.end()
            while content_start < close_start and text[content_start].isspace():
                content_start += 1
            end_title = label_end(text, content_start)
            if content_start < end_title <= close_start:
                output.append(Leaf(
                    "sentence", text[content_start:end_title],
                    (base + content_start, base + end_title),
                ))
                content_start = end_title
            output.extend(_parse_content(
                text[content_start:close_start], base + content_start
            ))

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

        if env in PROSE_ENVS:
            return _parse_content(block.raw, block.span[0])

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
