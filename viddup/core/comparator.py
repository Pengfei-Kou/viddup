"""
Similarity comparison and duplicate group detection.

Uses Union-Find (disjoint set) for O(n·α(n)) group merging,
and median Hamming distance for robust pHash comparison.
"""
from __future__ import annotations

import statistics
from collections.abc import Sequence
from dataclasses import dataclass

import imagehash

from viddup.core.database import FingerprintRecord

# ── pHash comparison ──────────────────────────────────────────────────────────

def compare_frame_hashes(
    hashes_a: list[str],
    hashes_b: list[str],
) -> float:
    """
    Compute perceptual similarity between two frame hash sequences.

    Uses median Hamming distance (more robust than mean — resistant to
    outlier frames like titles or fade-outs).

    Returns:
        Similarity in [0.0, 1.0] where 1.0 = identical.
    """
    n = min(len(hashes_a), len(hashes_b))
    if n == 0:
        return 0.0

    distances: list[int] = []
    for ha, hb in zip(hashes_a[:n], hashes_b[:n], strict=True):
        try:
            dist = imagehash.hex_to_hash(ha) - imagehash.hex_to_hash(hb)
            distances.append(dist)
        except Exception:
            continue  # skip unparseable hashes

    if not distances:
        return 0.0

    # pHash is a 64-bit hash, max Hamming distance = 64
    median_dist = statistics.median(distances)
    return max(0.0, 1.0 - (median_dist / 64.0))


# ── "Suggest keep" logic ──────────────────────────────────────────────────────

def suggest_keep(records: Sequence[FingerprintRecord]) -> FingerprintRecord:
    """
    Choose the best file to keep from a group of duplicates.

    Priority (descending):
    1. Highest pixel count (width × height)
    2. Largest file size (more data = less lossy)
    3. Lexicographically first path (deterministic tiebreak)
    """
    return max(
        records,
        key=lambda r: (r.pixel_count, r.file_size, [-ord(c) for c in r.path]),
    )


# ── Duplicate group data structures ──────────────────────────────────────────

@dataclass
class DuplicateGroup:
    group_id: int
    similarity: float          # 1.0 for exact, <1.0 for near-duplicates
    records: list[FingerprintRecord]
    suggested_keep: FingerprintRecord

    @property
    def total_size(self) -> int:
        return sum(r.file_size for r in self.records)

    @property
    def reclaimable_size(self) -> int:
        """Space that could be freed by keeping only the suggested file."""
        return self.total_size - self.suggested_keep.file_size


# ── Union-Find ────────────────────────────────────────────────────────────────

class _UnionFind:
    def __init__(self, n: int) -> None:
        self.parent = list(range(n))
        self.rank = [0] * n

    def find(self, x: int) -> int:
        if self.parent[x] != x:
            self.parent[x] = self.find(self.parent[x])  # path compression
        return self.parent[x]

    def union(self, x: int, y: int) -> None:
        px, py = self.find(x), self.find(y)
        if px == py:
            return
        if self.rank[px] < self.rank[py]:
            px, py = py, px
        self.parent[py] = px
        if self.rank[px] == self.rank[py]:
            self.rank[px] += 1


# ── Main comparison engine ────────────────────────────────────────────────────

def find_duplicates(
    records: list[FingerprintRecord],
    *,
    threshold: float,
    duration_tol: float,
) -> tuple[list[DuplicateGroup], list[DuplicateGroup]]:
    """
    Find exact and near-duplicate groups among *records*.

    Args:
        records:      Fingerprinted video records (with valid data).
        threshold:    Minimum similarity score to call two videos duplicates.
        duration_tol: Maximum relative duration difference for L2 pre-filter.

    Returns:
        (exact_groups, similar_groups)
        exact_groups:   Groups where all files share the same L1 file hash.
        similar_groups: Groups detected via L3 pHash comparison.
    """
    valid = [r for r in records if r.file_hash is not None]
    next_id = 1

    # ── L1: exact duplicates (group by file hash) ─────────────────────────────
    hash_to_records: dict[str, list[FingerprintRecord]] = {}
    for rec in valid:
        if rec.file_hash:
            hash_to_records.setdefault(rec.file_hash, []).append(rec)

    exact_groups: list[DuplicateGroup] = []
    exact_paths: set[str] = set()
    for recs in hash_to_records.values():
        if len(recs) < 2:
            continue
        group = DuplicateGroup(
            group_id=next_id,
            similarity=1.0,
            records=list(recs),
            suggested_keep=suggest_keep(recs),
        )
        exact_groups.append(group)
        for r in recs:
            exact_paths.add(r.path)
        next_id += 1

    # ── L3: near-duplicate detection ──────────────────────────────────────────
    # Only consider records that: have frame_hashes, have duration, are not
    # already in an exact-duplicate group.
    candidates = [
        r for r in valid
        if r.frame_hashes
        and r.duration
        and r.path not in exact_paths
    ]

    n = len(candidates)
    if n < 2:
        return exact_groups, []

    uf = _UnionFind(n)
    # Track best similarity per edge for reporting
    best_sim: dict[tuple[int, int], float] = {}

    for i in range(n):
        ri = candidates[i]
        for j in range(i + 1, n):
            rj = candidates[j]

            # L2 pre-filter: skip if durations differ too much
            if ri.duration and rj.duration:
                dur_diff = abs(ri.duration - rj.duration)
                avg_dur = (ri.duration + rj.duration) / 2
                if avg_dur > 0 and dur_diff / avg_dur > duration_tol:
                    continue

            # L3: pHash comparison
            assert ri.frame_hashes and rj.frame_hashes  # already filtered above
            sim = compare_frame_hashes(ri.frame_hashes, rj.frame_hashes)
            if sim >= threshold:
                pi, pj = uf.find(i), uf.find(j)
                edge = (min(pi, pj), max(pi, pj))
                best_sim[edge] = max(best_sim.get(edge, 0.0), sim)
                uf.union(i, j)

    # Collect groups
    groups_map: dict[int, list[int]] = {}
    for idx in range(n):
        root = uf.find(idx)
        groups_map.setdefault(root, []).append(idx)

    similar_groups: list[DuplicateGroup] = []
    for member_indices in groups_map.values():
        if len(member_indices) < 2:
            continue
        recs = [candidates[i] for i in member_indices]
        # Compute representative similarity (min across pairs in this group)
        sims = [
            best_sim.get(
                (min(uf.find(i), uf.find(j)), max(uf.find(i), uf.find(j))),
                threshold,
            )
            for idx_i, i in enumerate(member_indices)
            for j in member_indices[idx_i + 1:]
        ]
        group_sim = min(sims) if sims else threshold
        group = DuplicateGroup(
            group_id=next_id,
            similarity=round(group_sim, 4),
            records=recs,
            suggested_keep=suggest_keep(recs),
        )
        similar_groups.append(group)
        next_id += 1

    # Sort by reclaimable space (most valuable first)
    similar_groups.sort(key=lambda g: g.reclaimable_size, reverse=True)
    exact_groups.sort(key=lambda g: g.reclaimable_size, reverse=True)

    return exact_groups, similar_groups
