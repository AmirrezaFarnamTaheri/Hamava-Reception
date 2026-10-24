"""Small, dependency-free utilities shared by the research/measurement CLIs."""
from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from pathlib import Path
from typing import Any, Iterable, Sequence

DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
LETTERS = str.maketrans({"ي": "ی", "ى": "ی", "ك": "ک", "ـ": "", "\u200c": " ", "\u200d": " "})


def normalize_text(text: str) -> str:
    """Documented conservative orthographic normalization; no number-word guessing."""
    value = unicodedata.normalize("NFC", text).translate(DIGITS).translate(LETTERS).casefold()
    value = "".join(c if unicodedata.category(c)[0] in {"L", "N"} else " "
                    for c in value if unicodedata.category(c) != "Mn")
    return " ".join(value.split())


def digit_groups(text: str) -> tuple[str, ...]:
    return tuple(re.findall(r"[0-9]+", text.translate(DIGITS)))


def edit_distance(a: Sequence[Any], b: Sequence[Any]) -> int:
    if len(a) < len(b):
        a, b = b, a
    previous = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        current = [i]
        for j, y in enumerate(b, 1):
            current.append(min(current[-1] + 1, previous[j] + 1,
                               previous[j - 1] + (x != y)))
        previous = current
    return previous[-1]


def quantile(values: Iterable[float], q: float) -> float | None:
    ordered = sorted(values)
    if not ordered:
        return None
    index = (len(ordered) - 1) * q
    lower = math.floor(index)
    upper = math.ceil(index)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (index - lower)


def wilson(success: int, total: int, z: float = 1.959963984540054) -> list[float] | None:
    if total <= 0:
        return None
    if not 0 <= success <= total:
        raise ValueError("invalid_binomial_counts")
    p = success / total
    d = 1 + z * z / total
    center = (p + z * z / (2 * total)) / d
    radius = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / d
    return [0.0 if success == 0 else max(0.0, center - radius),
            1.0 if success == total else min(1.0, center + radius)]


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid_json_at_line_{line_number}") from exc
            if not isinstance(row, dict):
                raise ValueError(f"object_required_at_line_{line_number}")
            rows.append(row)
    if not rows:
        raise ValueError("empty_dataset")
    return rows


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def safe_reference(value: str) -> str:
    return sha256(value.encode("utf-8"))[:16]


def write_json(value: Any, path: Path | None = None) -> None:
    content = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    if path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    else:
        print(content, end="")

