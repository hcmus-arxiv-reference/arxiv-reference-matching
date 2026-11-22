"""LaTeX wrappers whose contents become children in the leaf tree."""
import re

LIST_ENVS = {"itemize", "enumerate", "description"}
PROSE_ENVS = {
    "abstract", "proof", "theorem", "lemma", "definition", "remark",
    "corollary", "example", "proposition", "thm", "framed",
    "quote", "quotation", "subequations",
}
PROSE_ENVS |= {name + "*" for name in PROSE_ENVS}

WRAPPER = re.compile(
    r"\\(?:begin|end)\s*\{(?P<env>"
    + "|".join(re.escape(name) for name in sorted(LIST_ENVS | PROSE_ENVS))
    + r")\}|\\item(?![a-zA-Z])"
)


def label_end(text: str, start: int) -> int:
    """Return the end of a complete bracket argument, otherwise start."""
    if not text.startswith("[", start):
        return start
    braces = 0
    brackets = 1
    index = start + 1
    while index < len(text):
        char = text[index]
        if char == "\\":
            index += 2
            continue
        if char == "{":
            braces += 1
        elif char == "}" and braces:
            braces -= 1
        elif not braces:
            if char == "[":
                brackets += 1
            elif char == "]":
                brackets -= 1
                if brackets == 0:
                    return index + 1
        index += 1
    return start


def only_markup(gap: str) -> bool:
    """Accept list setup only between the opening command and the first item."""
    pos = 0
    while pos < len(gap):
        if gap[pos].isspace():
            pos += 1
            continue
        token = WRAPPER.match(gap, pos)
        if token is None:
            return False
        pos = token.end()
        if token.group("env") in LIST_ENVS and token.group().startswith(r"\begin"):
            start = pos
            while pos < len(gap) and gap[pos].isspace():
                pos += 1
            pos = label_end(gap, pos)
            spacing = re.match(
                r"\s*\\vspace\*?\s*\{\s*[+-]?(?:\d+(?:\.\d*)?|\.\d+)"
                r"\s*(?:pt|mm|cm|in|em|ex)\s*\}", gap[pos:]
            )
            if spacing:
                pos += spacing.end()
            if not re.match(r"\s*\\item(?![a-zA-Z])", gap[pos:]):
                pos = start
    return True
