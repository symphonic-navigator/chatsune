import re
import string


def generate_monogram(name: str, existing: set[str]) -> str:
    letters = re.sub(r"[^a-zA-Z]", "", name)

    # Strategy 1: multi-part name — first + last initial
    parts = name.split()
    if len(parts) >= 2:
        first_initial = _first_letter(parts[0])
        last_initial = _first_letter(parts[-1])
        if first_initial and last_initial:
            candidate = (first_initial + last_initial).upper()
            if candidate not in existing:
                return candidate

    # Strategy 2: letter combinations from the name
    if letters:
        upper = letters.upper()
        for i in range(len(upper)):
            for j in range(i + 1, len(upper)):
                candidate = upper[i] + upper[j]
                if candidate not in existing:
                    return candidate
        candidate = upper[0] + upper[0]
        if candidate not in existing:
            return candidate

    # Strategy 3: no usable letters — iterate AA, AB, AC...
    for first in string.ascii_uppercase:
        for second in string.ascii_uppercase:
            candidate = first + second
            if candidate not in existing:
                return candidate

    return "??"


def _first_letter(part: str) -> str | None:
    for ch in part:
        if ch.isalpha():
            return ch
    return None
