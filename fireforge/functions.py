import re
import os
from typing import Any,ClassVar
from .consts import DOTENV_PLACEHOLDER_PATTERN

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

def parse_config(config: Any) -> Any:
    """
    Parse value with ${VAR:default} or ${VAR} syntax (original interface).
    """    
    # If input is a dictionary, process it recursively
    match config:
        case dict():
            return {key: parse_config(value) for key, value in config.items()}
        case list():
            return [parse_config(item) for item in config]
        case str():
            def replace_match(match):
                var_name = match.group(1)  # The variable name
                default = match.group(2)   # The default value (if any)
                print("var_name : ", var_name)
                print("default : ", default)
                # print("os.getenv(var_name, defa) : ", os.getenv(var_name, default if default is not None else ""))
                return os.getenv(var_name, default if default is not None else "")
            return re.sub(DOTENV_PLACEHOLDER_PATTERN, replace_match, config)
        case _:
            return config