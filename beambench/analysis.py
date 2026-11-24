"""Measure light on immutable, displayed original coordinates."""

import cv2
import numpy as np

from image_lab.validation import Invalid

from . import frame, model


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


def clipping(light, settings):
    rows, marks = [], []
    low, high = settings["clip_low"], settings["clip_high"]
    for index, cell in grid_boxes(settings["box"], 4):
        values = box_view(light, cell)
        shadows = int(np.count_nonzero(values <= low))
        highlights = int(np.count_nonzero(values >= high))
        x, y = center(cell)
        rows.append({"cell": index, "x": x, "y": y, "dark": shadows, "bright": highlights, "pixels": values.size})
        fraction = min(255, (shadows + highlights) * 255 / values.size)
        marks.append({"kind": "rect", "box": cell, "level": fraction})
    return result("clipping", ["cell", "x", "y", "dark", "bright", "pixels"], rows,
                  {"Dark pixels": sum(row["dark"] for row in rows),
                   "Bright pixels": sum(row["bright"] for row in rows), "Levels": f"{low} · {high}"}, marks)


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
    width = light.shape[1]
    # A positive shift means the reference photo's content sits that many pixels to the
    # right of the active photo; only the overlapping columns carry both photos' pixels.
    direction = settings["shift_x"] if settings["source"] == "a" else -settings["shift_x"]
    left, top, right, bottom = settings["box"]
    low, high = max(left, -direction), min(right, width - 1 - direction)
    if low > high:
        raise Invalid("The shift moves the reference photo outside the inspection box.")
    for index, cell in grid_boxes(settings["box"], 4):
        cell_left, cell_top, cell_right, cell_bottom = cell
        lo, hi = max(cell_left, low), min(cell_right, high)
        x, y = center(cell)
        if lo > hi:
            rows.append({"cell": index, "x": x, "y": y, "active": None, "reference": None,
                         "change": None, "pixels": 0})
            continue
        source = box_view(light, [lo, cell_top, hi, cell_bottom])
        reference = box_view(other, [lo + direction, cell_top, hi + direction, cell_bottom])
        change = float((source - reference).mean())
        rows.append({"cell": index, "x": x, "y": y, "active": round(float(source.mean()), 2),
                     "reference": round(float(reference.mean()), 2), "change": round(change, 2),
                     "pixels": int(source.size)})
        marks.append({"kind": "rect", "box": [lo, cell_top, hi, cell_bottom],
                      "level": min(abs(change) * 5, 255)})
    base = box_view(light, [low, top, high, bottom])
    counterpart = box_view(other, [low + direction, top, high + direction, bottom])
    return result("compare", ["cell", "x", "y", "active", "reference", "change", "pixels"], rows,
                  {"Compared pixels": int(base.size),
                   "Mean difference": round(float((base - counterpart).mean()), 2),
                   "Mean absolute": round(float(np.abs(base - counterpart).mean()), 2),
                   "Reference shift X": direction,
                   "Box overlap %": round(100 * (high - low + 1) / (right - left + 1), 1)}, marks)


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
    handlers = {"map": level_map, "footprint": footprint, "falloff": falloff, "clipping": clipping}
    return handlers[mode](light, settings)
