"""Multi-objective helpers (maximisation): fast non-dominated sort and crowding distance (NSGA-II)."""
from __future__ import annotations


def dominates(a, b) -> bool:
    return all(x >= y for x, y in zip(a, b)) and any(x > y for x, y in zip(a, b))


def non_dominated_sort(vecs: list[list[float]]) -> list[list[int]]:
    n = len(vecs)
    S = [[] for _ in range(n)]
    cnt = [0] * n
    fronts = [[]]
    for p in range(n):
        for q in range(n):
            if p == q:
                continue
            if dominates(vecs[p], vecs[q]):
                S[p].append(q)
            elif dominates(vecs[q], vecs[p]):
                cnt[p] += 1
        if cnt[p] == 0:
            fronts[0].append(p)
    i = 0
    while fronts[i]:
        nxt = []
        for p in fronts[i]:
            for q in S[p]:
                cnt[q] -= 1
                if cnt[q] == 0:
                    nxt.append(q)
        i += 1
        fronts.append(nxt)
    return [f for f in fronts if f]


def crowding_distance(vecs: list[list[float]]) -> list[float]:
    n = len(vecs)
    if n <= 2:
        return [float("inf")] * n
    d = [0.0] * n
    for m in range(len(vecs[0])):
        order = sorted(range(n), key=lambda i: vecs[i][m])
        lo, hi = vecs[order[0]][m], vecs[order[-1]][m]
        d[order[0]] = d[order[-1]] = float("inf")
        if hi == lo:
            continue
        for k in range(1, n - 1):
            d[order[k]] += (vecs[order[k + 1]][m] - vecs[order[k - 1]][m]) / (hi - lo)
    return d
