"""Render a claim's narrative.md: human-written explanation whose numbers come from the record.

Placeholders look like {{ path }} or {{ path | filter }}. Paths are dotted into the built
claim record; list items can be selected by index (reproductions.0) or by key
(comparisons[aspect=runtime_seconds]). Unresolved placeholders are a validation error, so
prose can never quote a number the record does not contain.
"""

from __future__ import annotations

import math
import re

PLACEHOLDER = re.compile(r"\{\{\s*([^{}|]+?)\s*(?:\|\s*([a-z_]+)\s*)?\}\}")
SELECTOR = re.compile(r"^([A-Za-z0-9_-]+)\[([A-Za-z0-9_-]+)=([^\]]+)\]$")
SUPERSCRIPTS = str.maketrans("0123456789-", "⁰¹²³⁴⁵⁶⁷⁸⁹⁻")
GENERATED_BANNER = "<!-- Rendered by `qacclaims build` from narrative.md. Edit narrative.md; this file is regenerated. -->\n\n"


class NarrativeError(ValueError):
    pass


def lookup(record, path: str):
    node = record
    for token in path.split("."):
        selector = SELECTOR.match(token)
        if selector:
            name, key, value = selector.groups()
            node = node[name]
            matches = [item for item in node if str(item.get(key)) == value]
            if not matches:
                raise NarrativeError(f"no item with {key}={value} in {name}")
            node = matches[0]
        elif isinstance(node, list):
            node = node[int(token)]
        elif isinstance(node, dict) and token in node:
            node = node[token]
        else:
            raise NarrativeError(f"'{token}' not found")
    return node


def _trim(text: str) -> str:
    return text.rstrip("0").rstrip(".") if "." in text else text


def filter_n(value):
    return f"{int(round(float(value))):,}"


def filter_sci(value):
    value = float(value)
    exponent = int(math.floor(math.log10(abs(value))))
    mantissa = value / 10**exponent
    return f"{_trim(f'{mantissa:.2f}')} × 10{str(exponent).translate(SUPERSCRIPTS)}"


def filter_million(value):
    return f"{_trim(f'{float(value) / 1e6:.2f}')} million"


def filter_hours(value):
    seconds = float(value)
    if seconds < 3600:
        return f"{_trim(f'{seconds / 60:.1f}')} minutes"
    if seconds > 48 * 3600:
        return f"{_trim(f'{seconds / 86400:.1f}')} days"
    return f"{_trim(f'{seconds / 3600:.1f}')} hours"


def filter_x(value):
    ratio = float(value)
    return f"{ratio:.2f}×" if abs(ratio - 1) < 0.2 else f"{ratio:.1f}×"


def filter_pct(value):
    return f"{(float(value) - 1) * 100:+.0f}%"


def filter_pctabs(value):
    return f"{abs(float(value) - 1) * 100:.0f}%"


def filter_g(value):
    return _trim(f"{float(value):.6g}") if isinstance(value, (int, float)) else str(value)


FILTERS = {
    "n": filter_n,
    "sci": filter_sci,
    "million": filter_million,
    "hours": filter_hours,
    "x": filter_x,
    "pct": filter_pct,
    "pctabs": filter_pctabs,
    "g": filter_g,
    "raw": str,
}


def render(text: str, record) -> tuple[str, list[str]]:
    """Return (rendered text, list of problems). Problems leave the placeholder in place."""
    problems: list[str] = []

    def substitute(match: re.Match) -> str:
        path, filter_name = match.group(1).strip(), match.group(2)
        try:
            value = lookup(record, path)
        except (NarrativeError, KeyError, IndexError, ValueError, TypeError) as error:
            problems.append(f"{{{{ {path} }}}}: {error}")
            return match.group(0)
        if filter_name is None:
            return str(value)
        if filter_name not in FILTERS:
            problems.append(f"{{{{ {path} | {filter_name} }}}}: unknown filter")
            return match.group(0)
        try:
            return FILTERS[filter_name](value)
        except Exception as error:  # noqa: BLE001 - surfaced as a validation problem
            problems.append(f"{{{{ {path} | {filter_name} }}}}: {error}")
            return match.group(0)

    return PLACEHOLDER.sub(substitute, text), problems
