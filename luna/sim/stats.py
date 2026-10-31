"""Statistics helpers: Wilson CI, paired differences (common random numbers), Wilcoxon-free summaries."""
from __future__ import annotations

import math


def wilson(k: float, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return (max(0.0, c - h), min(1.0, c + h))


def mean_ci(xs: list[float], z: float = 1.96) -> tuple[float, float, float]:
    n = len(xs)
    if n == 0:
        return (0.0, 0.0, 0.0)
    m = sum(xs) / n
    if n == 1:
        return (m, m, m)
    var = sum((x - m) ** 2 for x in xs) / (n - 1)
    h = z * math.sqrt(var / n)
    return (m, m - h, m + h)


def paired_diff(a: list[float], b: list[float], z: float = 1.96) -> dict:
    """a, b evaluated on the same seeds (CRN). Returns mean(b-a) with CI and a sign summary."""
    d = [y - x for x, y in zip(a, b)]
    m, lo, hi = mean_ci(d, z)
    return {"delta": m, "ci": (lo, hi), "n": len(d), "better": sum(1 for x in d if x > 0),
            "worse": sum(1 for x in d if x < 0), "significant": lo > 0 or hi < 0}


def n_for_margin(margin: float, p: float = 0.5, z: float = 1.96) -> int:
    """Battles needed so the 95 % CI half-width of a win rate is <= margin."""
    return math.ceil(z * z * p * (1 - p) / (margin * margin))
