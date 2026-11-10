LIKE_ESCAPE = "\\"


def prefix_pattern(term: str) -> str:
    """`term%` for an ILIKE with `escape=LIKE_ESCAPE`: backslash, percent and
    underscore in the term match literally instead of acting as wildcards."""

    for char in (LIKE_ESCAPE, "%", "_"):
        term = term.replace(char, LIKE_ESCAPE + char)

    return f"{term}%"
