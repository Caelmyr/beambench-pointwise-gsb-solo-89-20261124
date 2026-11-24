"""Recommend an even, continuously lit placement segment along a profile line.

The finder only works from the displayed, immutable profile samples. Pixels
below the minimum brightness split the line into separate runs (a dark trench
is never bridged), and every candidate window must stay within both the minimum
brightness and the user's evenness tolerance. Candidates are scored by both
usable width and the tolerance headroom left for shoot-to-shoot fluctuation.
"""

from collections import deque

import numpy as np


def lit_runs(mask):
    """Split a boolean line into contiguous runs of acceptable samples."""
    runs, start = [], None
    for index, okay in enumerate(mask):
        if okay and start is None:
            start = index
        elif not okay and start is not None:
            runs.append((start, index - 1))
            start = None
    if start is not None:
        runs.append((start, len(mask) - 1))
    return runs


def pareto_filter(candidates):
    """Keep only windows not dominated on both width and tolerance margin.

    Scanned from widest to narrowest, a window survives only when its margin
    is strictly higher than every wider window seen so far.
    """
    ordered = sorted(candidates, key=lambda item: (-item["width"], -item["margin"], item["start"]))
    front, best_margin = [], -1.0
    for candidate in ordered:
        if candidate["margin"] > best_margin:
            front.append(candidate)
            best_margin = candidate["margin"]
    return front


def feasible_windows(values, run_start, run_end, tolerance, min_width):
    """Scan one lit run, yielding the widest feasible window at each right edge.

    Monotonic deques track the running min and max. For every right edge the
    left edge advances to the earliest start that still satisfies the
    tolerance, so each maximal feasible window is examined exactly once.
    """
    min_q, max_q = deque(), deque()
    left = run_start
    for right in range(run_start, run_end + 1):
        value = values[right]
        while min_q and values[min_q[-1]] >= value:
            min_q.pop()
        min_q.append(right)
        while max_q and values[max_q[-1]] <= value:
            max_q.pop()
        max_q.append(right)
        while values[max_q[0]] - values[min_q[0]] > tolerance:
            left += 1
            if min_q[0] < left:
                min_q.popleft()
            if max_q[0] < left:
                max_q.popleft()
        width = right - left + 1
        if width < min_width:
            continue
        window = values[left:right + 1]
        spread = float(np.ptp(window))
        yield {
            "start": left, "end": right, "width": width,
            "min": round(float(window.min()), 3), "max": round(float(window.max()), 3),
            "spread": round(spread, 3), "margin": round(tolerance - spread, 3),
        }

def reason(candidate, tolerance):
    spread = candidate["spread"]
    headroom = tolerance - spread
    return (
        f"{candidate['width']} px wide with a {spread:.2f}-level brightness swing, "
        f"leaving {headroom:.2f} levels of the {tolerance:g}-level tolerance in reserve."
    )


def recommend(values, minimum, min_width, tolerance, limit=6):
    """Build ranked placement suggestions for one measured line.

    Returns ``(selected, placement)``. ``selected`` is the chosen index range or
    ``None`` when nothing on the line meets the requirements; in that case the
    caller keeps its existing full-line measurement untouched.
    """
    values = np.asarray(values, dtype=np.float64)
    length = int(values.size)
    mask = values >= minimum
    runs = lit_runs(mask)
    candidates, run_blocks = [], []
    for run_start, run_end in runs:
        run_values = values[run_start:run_end + 1]
        run_spread = round(float(np.ptp(run_values)), 3)
        run_blocks.append({
            "start": run_start, "end": run_end,
            "width": run_end - run_start + 1,
            "meets_width": run_end - run_start + 1 >= min_width,
            "min": round(float(run_values.min()), 3), "max": round(float(run_values.max()), 3),
            "spread": run_spread,
        })
        if run_end - run_start + 1 >= min_width:
            candidates.extend(feasible_windows(values, run_start, run_end, tolerance, min_width))
    front = pareto_filter(candidates)
    if not front:
        return None, {
            "minimum": minimum, "min_width": min_width, "tolerance": tolerance,
            "line_width": length, "runs": run_blocks, "candidates": [], "selected": None,
            "message": "No continuous segment on this line meets all three requirements; the full-line measurement is kept.",
        }
    widths = [candidate["width"] for candidate in front]
    margins = [candidate["margin"] for candidate in front]
    width_span = max(widths) - min(widths)
    margin_span = max(margins) - min(margins)
    for candidate in front:
        # Normalize against the actual trade-off range on this line so that an
        # easily met tolerance cannot let the smallest window win on margin alone.
        width_score = 1.0 if width_span == 0 else (candidate["width"] - min(widths)) / width_span
        margin_score = 1.0 if margin_span == 0 else (candidate["margin"] - min(margins)) / margin_span
        candidate["width_score"] = round(width_score, 4)
        candidate["margin_score"] = round(margin_score, 4)
        # Equal weighting: half placement capacity, half fluctuation reserve.
        candidate["score"] = round(0.5 * width_score + 0.5 * margin_score, 4)
        candidate["reason"] = reason(candidate, tolerance)
    ranked = sorted(front, key=lambda item: (-item["score"], -item["width"], item["spread"], item["start"]))
    ranked = ranked[:limit]
    selected = ranked[0]
    placement_block = {
        "minimum": minimum, "min_width": min_width, "tolerance": tolerance,
        "line_width": length, "runs": run_blocks, "candidates": ranked,
        "selected": {"start": selected["start"], "end": selected["end"]},
        "message": selected["reason"],
    }
    return [selected["start"], selected["end"]], placement_block
