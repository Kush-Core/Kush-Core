"""Roman numerals for the Chronicle's dates, e.g. 2 Nov 2026 -> II·XI·MMXXVI."""

from __future__ import annotations

from datetime import date

_NUMERALS = (
    (1000, "M"), (900, "CM"), (500, "D"), (400, "CD"),
    (100, "C"), (90, "XC"), (50, "L"), (40, "XL"),
    (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I"),
)


def to_roman(n: int) -> str:
    """Standard subtractive Roman numeral for 1..3999."""
    if isinstance(n, bool) or not isinstance(n, int) or not 1 <= n <= 3999:
        raise ValueError(f"Roman numerals cover 1..3999, got {n!r}")
    out = []
    for value, symbol in _NUMERALS:
        count, n = divmod(n, value)
        out.append(symbol * count)
    return "".join(out)


def roman_date(d: date) -> str:
    """Day·month·year, each in Roman numerals, joined by a middle dot (U+00B7)."""
    return f"{to_roman(d.day)}·{to_roman(d.month)}·{to_roman(d.year)}"
