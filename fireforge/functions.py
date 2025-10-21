import re

__all__ = ["to_snake_case", "to_pascal_case"]

_SPLIT_RE = re.compile(
    r"""
    ([a-z0-9])([A-Z])        # aB -> a B
    |([A-Z]+)([A-Z][a-z0-9]) # ABBRWord -> ABBR Word
    |[^0-9A-Za-z]+           # delimiters -> space
    """,
    re.VERBOSE,
)


def _parts(value: str) -> list[str]:
    if not isinstance(value, str):  # pyright: ignore[reportUnnecessaryIsInstance]
        return []  # pyright: ignore[reportUnreachable]

    value = _SPLIT_RE.sub(
        lambda mo: (mo.group(1) or mo.group(3) or "")
        + (mo.group(2) or mo.group(4) or "")
        + " ",
        value,
    )

    return [p for p in value.split() if p]


def to_snake_case(value: str) -> str:
    return "_".join(part.lower() for part in _parts(value))


def to_pascal_case(value: str) -> str:
    return "".join(part.capitalize() for part in _parts(value))
