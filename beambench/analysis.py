"""Measure light on immutable, displayed original coordinates."""

import cv2
import numpy as np

from image_lab.validation import Invalid

from . import frame, model

CLIPPING_NOISE_FLOOR = 4
CLIPPING_MARK_BUDGET = 100_000
CHANNELS = ("R", "G", "B")


def result(mode, columns, rows, summary, marks=(), chart=()):
    return {
        "mode": mode, "heading": model.MODES[mode], "columns": columns,
        "rows": rows, "summary": summary, "marks": list(marks), "chart": list(chart),
    }


def statistics(values):
    return {
        "min": round(float(values.min()), 2), "mean": round(float(values.mean()), 2),
        "max": round(float(values.max()), 2), "spread": round(float(np.ptp(values)), 2),
    }


def box_view(array, box):
    left, top, right, bottom = box
    return array[top:bottom + 1, left:right + 1]


def profile(light, settings, mode):
    left, top, right, bottom = settings["box"]
    if mode == "across":
        y = settings["row"]
        coords = [(x, y) for x in range(left, right + 1)]
    else:
        x = settings["column"]
        coords = [(x, y) for y in range(top, bottom + 1)]
    values = np.array([light[y, x] for x, y in coords])
    rows = [{"x": x, "y": y, "luma": round(float(value), 3)} for (x, y), value in zip(coords, values)]
    stats = statistics(values)
    return result(mode, ["x", "y", "luma"], rows,
                  {"Samples": len(rows), "Average": stats["mean"], "Spread": stats["spread"]},
                  [{"kind": "line", "points": [coords[0], coords[-1]]}],
                  [row["luma"] for row in rows])


def grid_boxes(box, divisions=6):
    left, top, right, bottom = box
    across = min(divisions, right - left + 1)
    down = min(divisions, bottom - top + 1)
    xs = np.linspace(left, right + 1, across + 1, dtype=int)
    ys = np.linspace(top, bottom + 1, down + 1, dtype=int)
    return [(index, [int(x0), int(y0), int(x1) - 1, int(y1) - 1])
            for index, (y0, y1, x0, x1) in enumerate(
                ((y0, y1, x0, x1) for y0, y1 in zip(ys[:-1], ys[1:]) for x0, x1 in zip(xs[:-1], xs[1:])), 1)]


def center(box):
    left, top, right, bottom = box
    return (left + right) // 2, (top + bottom) // 2


def level_map(light, settings):
    rows, marks = [], []
    for index, cell in grid_boxes(settings["box"]):
        values = box_view(light, cell)
        measures = statistics(values)
        x, y = center(cell)
        rows.append({"cell": index, "x": x, "y": y, "average": measures["mean"], "spread": measures["spread"]})
        marks.append({"kind": "rect", "box": cell, "level": measures["mean"]})
    return result("map", ["cell", "x", "y", "average", "spread"], rows,
                  {"Cells": len(rows), "Frame average": statistics(box_view(light, settings["box"]))["mean"]}, marks)


def footprint(light, settings):
    box = settings["box"]
    left, top, _, _ = box
    roi = box_view(light, box)
    mask = (roi >= settings["threshold"]).astype("uint8")
    count, labels, info, centroids = cv2.connectedComponentsWithStats(mask, connectivity=8)
    # Keep trace detail for the largest components and retain full pixel coverage in the totals.
    order = sorted(range(1, count), key=lambda index: -int(info[index, cv2.CC_STAT_AREA]))
    rows, marks = [], []
    for rank, index in enumerate(order[:16], 1):
        x, y, width, height, area = map(int, info[index])
        section = labels[y:y + height, x:x + width] == index
        cx, cy = centroids[index]
        contour, _ = cv2.findContours(section.astype("uint8"), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for outline in contour:
            simplified = cv2.approxPolyDP(outline, 1.0, True).reshape(-1, 2)
            points = [[int(col) + x + left, int(row) + y + top] for col, row in simplified]
            if len(points) > 1:
                marks.append({"kind": "outline", "points": points})
        rows.append({"island": rank, "center_x": round(float(cx) + left, 1), "center_y": round(float(cy) + top, 1),
                     "width": width, "height": height, "area": area})
    area = int(mask.sum())
    return result("footprint", ["island", "center_x", "center_y", "width", "height", "area"], rows,
                  {"Light level": settings["threshold"], "Islands": count - 1,
                   "Lit pixels": area, "Coverage %": round(100 * area / roi.size, 2)}, marks)


def falloff(light, settings):
    left, top, right, bottom = settings["box"]
    ox, oy = settings["origin"]
    step = settings["radius_step"]
    values = box_view(light, settings["box"])
    yy, xx = np.ogrid[top:bottom + 1, left:right + 1]
    distance = np.hypot(xx - ox, yy - oy)
    bands = (distance / step).astype(np.int32)
    number = np.bincount(bands.ravel())
    total = np.bincount(bands.ravel(), values.ravel())
    rows = [{"from_px": index * step, "to_px_exclusive": (index + 1) * step,
             "samples": int(size), "luma": round(float(total[index] / size), 3)}
            for index, size in enumerate(number) if size]
    rings = len(rows)
    radii = [rows[int(index)]["to_px_exclusive"] for index in np.linspace(0, rings - 1, min(7, rings))]
    marks = [{"kind": "circle", "center": [ox, oy], "radius": radius} for radius in radii]
    return result("falloff", ["from_px", "to_px_exclusive", "samples", "luma"], rows,
                  {"Bands": rings, "Step px": step, "Origin": f"{ox}, {oy}"}, marks,
                  [row["luma"] for row in rows])


def _pixel_runs(classes, left, top):
    """Row spans per channel class, in original photo coordinates."""
    runs = {"single": [], "multi": []}
    for name, value in (("single", 1), ("multi", 2)):
        for row in range(classes.shape[0]):
            padded = np.concatenate(([0], (classes[row] == value).astype(np.int8), [0]))
            edges = np.flatnonzero(np.diff(padded))
            for start, stop in zip(edges[::2], edges[1::2]):
                runs[name].append([row + top, int(start) + left, int(stop) + left - 1])
    return runs


def _region_reason(best, other):
    def label(item):
        return f"{item['channels']} region ({item['area']} px, {item['samples']} clipped channel values)"
    if other is None:
        return f"Only clipped region in this cell: {label(best)}."
    if best["samples"] != other["samples"]:
        basis = f"{best['samples']} vs {other['samples']} clipped channel values"
    elif best["area"] != other["area"]:
        basis = f"{best['area']} vs {other['area']} clipped pixels"
    elif len(best["channel_set"]) != len(other["channel_set"]):
        basis = f"{len(best['channel_set'])} vs {len(other['channel_set'])} lost channels"
    else:
        basis = "nearer the cell center"
    return f"Re-shoot {label(best)} before {label(other)}: {basis}."


def _cell_regions(shaded, labels, channels, keep, cell, box):
    """Clipped regions of one grid cell, ranked by actual area and lost channels."""
    column, row = cell[0] - box[0], cell[1] - box[1]
    height, width = cell[3] - cell[1] + 1, cell[2] - cell[0] + 1
    local = labels[row:row + height, column:column + width]
    counts = channels[row:row + height, column:column + width]
    clipped = shaded[row:row + height, column:column + width]
    flat = local.ravel()
    marked = flat > 0
    if not marked.any():
        return None, None
    ids, inverse = np.unique(flat[marked], return_inverse=True)
    size = np.bincount(inverse).astype(float)
    size[~keep[ids] | (size < CLIPPING_NOISE_FLOOR)] = 0
    if not size.any():
        return None, None
    weights = np.maximum(size, 1)
    samples = np.bincount(inverse, weights=counts.ravel()[marked].astype(float))
    single = np.bincount(inverse, weights=counts.ravel()[marked] == 1)
    multi = np.bincount(inverse, weights=counts.ravel()[marked] >= 2)
    lost = np.array([np.bincount(inverse, weights=clipped[..., index].ravel()[marked].astype(float))
                     for index in range(3)]) > 0
    ys, xs = np.divmod(np.flatnonzero(marked), width)
    centroid_x = np.bincount(inverse, weights=xs.astype(float)) / weights
    centroid_y = np.bincount(inverse, weights=ys.astype(float)) / weights
    reach = (centroid_x - width / 2) ** 2 + (centroid_y - height / 2) ** 2
    reach[size == 0] = np.inf
    order = np.lexsort((reach, -size, -lost.sum(axis=0), -samples))[:2]
    candidates = []
    for position in order:
        identifier = int(ids[position])
        if not size[position]:
            continue
        mask = local == identifier
        found = [CHANNELS[index] for index in range(3) if lost[index, position]]
        nearest = _nearest(mask, centroid_x[position], centroid_y[position])
        candidates.append({
            "id": identifier, "area": int(size[position]), "samples": int(samples[position]),
            "channel_set": found, "channels": "+".join(found),
            "single": int(single[position]), "multi": int(multi[position]),
            "mask": mask, "counts": counts,
            "pick": [nearest[0] + cell[0], nearest[1] + cell[1]],
        })
    best = candidates[0] if candidates else None
    return best, (candidates[1] if len(candidates) > 1 else None)


def _nearest(mask, x, y):
    ys, xs = np.nonzero(mask)
    index = int(np.argmin((xs - x) ** 2 + (ys - y) ** 2))
    return int(xs[index]), int(ys[index])


def clipping(light, rgb, settings):
    rows, marks = [], []
    low, high = settings["clip_low"], settings["clip_high"]
    box = settings["box"]
    shaded = box_view(rgb, box) >= high
    channels = shaded.sum(axis=2)
    union = (channels > 0).astype("uint8")
    count, labels, info, _ = cv2.connectedComponentsWithStats(union, connectivity=8)
    areas = info[:, cv2.CC_STAT_AREA]
    keep = (areas >= CLIPPING_NOISE_FLOOR) & (np.arange(count) > 0)
    specks = np.array([identifier for identifier in range(1, count)
                       if 0 < int(areas[identifier]) < CLIPPING_NOISE_FLOOR], dtype=int)
    speck_pixels = int(areas[specks].sum()) if specks.size else 0
    picks = singles = multis = 0
    for index, cell in grid_boxes(box, 4):
        values = box_view(light, cell)
        shadows = int(np.count_nonzero(values <= low))
        highlights = int(np.count_nonzero(values >= high))
        x, y = center(cell)
        row = {"cell": index, "x": x, "y": y, "dark": shadows, "bright": highlights,
               "pixels": values.size, "pick_x": "", "pick_y": "", "area": "", "channels": "",
               "single": "", "multi": "", "why": ""}
        best, other = _cell_regions(shaded, labels, channels, keep, cell, box)
        fraction = min(255, (shadows + highlights) * 255 / values.size)
        marks.append({"kind": "rect", "box": cell, "level": fraction})
        if best:
            singles += best["single"]
            multis += best["multi"]
            row.update({"pick_x": best["pick"][0], "pick_y": best["pick"][1], "area": best["area"],
                        "channels": best["channels"], "single": best["single"], "multi": best["multi"],
                        "why": _region_reason(best, other)})
            classes = best["mask"] * np.where(best["counts"] >= 2, 2, 1).astype("uint8")
            runs = _pixel_runs(classes, cell[0], cell[1])
            for name in ("single", "multi"):
                for chunk in range(0, len(runs[name]), CLIPPING_MARK_BUDGET):
                    marks.append({"kind": "clip_pixels", "class": name,
                                  "runs": runs[name][chunk:chunk + CLIPPING_MARK_BUDGET]})
            picks += 1
        rows.append(row)
    return result("clipping", ["cell", "x", "y", "dark", "bright", "pixels", "pick_x", "pick_y",
                               "area", "channels", "single", "multi", "why"], rows,
                  {"Dark pixels": sum(row["dark"] for row in rows),
                   "Bright pixels": sum(row["bright"] for row in rows), "Levels": f"{low} · {high}",
                   "Re-shoot regions": picks, "Single-channel px": singles,
                   "Multi-channel px": multis, "Ignored specks": f"{len(specks)} · {speck_pixels} px"},
                  marks)


def color_cast(rgb, settings):
    rows = []
    for index, cell in grid_boxes(settings["box"], 3):
        r, g, b = box_view(rgb, cell).mean(axis=(0, 1))
        x, y = center(cell)
        rows.append({"cell": index, "x": x, "y": y, "red": round(float(r), 2), "green": round(float(g), 2),
                     "blue": round(float(b), 2), "red_minus_blue": round(float(r - b), 2)})
    warm = max(rows, key=lambda row: row["red_minus_blue"])
    cool = min(rows, key=lambda row: row["red_minus_blue"])
    return result("cast", ["cell", "x", "y", "red", "green", "blue", "red_minus_blue"], rows,
                  {"Warmest cell": warm["cell"], "Coolest cell": cool["cell"]})


def comparison(light, other, settings):
    rows, marks = [], []
    base = box_view(light, settings["box"])
    counterpart = box_view(other, settings["box"])
    for index, cell in grid_boxes(settings["box"], 4):
        source, reference = box_view(light, cell), box_view(other, cell)
        x, y = center(cell)
        shift = float((source - reference).mean())
        rows.append({"cell": index, "x": x, "y": y, "active": round(float(source.mean()), 2),
                     "reference": round(float(reference.mean()), 2), "change": round(shift, 2)})
        marks.append({"kind": "rect", "box": cell, "level": min(abs(shift) * 5, 255)})
    return result("compare", ["cell", "x", "y", "active", "reference", "change"], rows,
                  {"Compared pixels": base.size, "Mean difference": round(float((base - counterpart).mean()), 2),
                   "Mean absolute": round(float(np.abs(base - counterpart).mean()), 2)}, marks)


def inspect(library, record, mode, settings):
    rgb = frame.pixels(library, record, settings["source"])
    light = frame.luma(rgb)
    if mode in ("across", "down"):
        return profile(light, settings, mode)
    if mode == "cast":
        return color_cast(rgb, settings)
    if mode == "compare":
        other = "b" if settings["source"] == "a" else "a"
        if other not in record["sources"]:
            raise Invalid("Add a second aligned photo to compare lighting.")
        measured = comparison(light, frame.luma(frame.pixels(library, record, other)), settings)
        measured["comparison_source"] = other
        return measured
    handlers = {"map": level_map, "footprint": footprint, "falloff": falloff}
    if mode == "clipping":
        return clipping(light, rgb, settings)
    return handlers[mode](light, settings)
