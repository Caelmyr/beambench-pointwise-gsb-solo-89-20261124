"""Write reports with unchanged source dimensions and pixel coordinates."""

import csv
from io import StringIO

from PIL import Image, ImageDraw

from .frame import encode


def table(report):
    text = StringIO(newline="")
    fields = ["source", *report["columns"]]
    if "comparison_source" in report:
        fields.insert(1, "comparison_source")
    sources = {key: report[key] for key in fields if key in ("source", "comparison_source")}
    writer = csv.DictWriter(text, fieldnames=fields)
    writer.writeheader()
    writer.writerows({**sources, **row} for row in report["rows"])
    return text.getvalue()


def overlay(path, report):
    with Image.open(path) as source:
        original = source.convert("RGBA")
    layer = Image.new("RGBA", original.size)
    draw = ImageDraw.Draw(layer)
    box = report["settings"]["box"]
    draw.rectangle(tuple(box), outline=(79, 225, 223, 255), width=2)
    color = (255, 208, 101, 255)
    for item in report["marks"]:
        kind = item["kind"]
        if kind == "rect":
            level = item["level"]
            shade = (255, int(80 + level * 0.45), 48, int(20 + level * 0.44))
            draw.rectangle(tuple(item["box"]), fill=shade, outline=(225, 232, 244, 128), width=1)
        elif kind == "circle":
            x, y = item["center"]
            r = item["radius"]
            draw.ellipse((x-r, y-r, x+r, y+r), outline=color, width=2)
        else:
            points = [tuple(coords) for coords in item["points"]]
            if kind == "outline":
                points.append(points[0])
            draw.line(points, fill=color, width=2)
    return encode(Image.alpha_composite(original, layer).convert("RGB"))
