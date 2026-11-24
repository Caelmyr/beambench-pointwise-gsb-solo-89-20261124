"""Validate source-space geometry and current lighting-test settings."""

from math import isfinite

from image_lab.validation import Invalid

MAX_PIXELS = 4_000_000
MAX_UPLOAD = 14 * 1024 * 1024
MODES = {
    "across": "Horizontal profile",
    "down": "Vertical profile",
    "map": "Illumination map",
    "footprint": "Light footprint",
    "falloff": "Radial falloff",
    "clipping": "Exposure clipping",
    "cast": "Color cast",
    "compare": "Photo comparison",
}


def document(value):
    if not isinstance(value, dict):
        raise Invalid("Send a settings object.")
    return value


def text(value, default="", maximum=80):
    if value is None or value == "":
        return default
    if not isinstance(value, str) or len(value) > maximum:
        raise Invalid(f"Use no more than {maximum} characters.")
    return value.strip() or default


def number(value, low, high, label):
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not isfinite(value) or not low <= value <= high:
        raise Invalid(f"{label} must be between {low} and {high}.")
    return value


def integer(value, low, high, label):
    if not isinstance(value, int) or isinstance(value, bool):
        raise Invalid(f"{label} must be a whole pixel coordinate.")
    return number(value, low, high, label)


def point(value, width, height):
    if not isinstance(value, list) or len(value) != 2:
        raise Invalid("Select a point on the photo.")
    return [integer(value[0], 0, width - 1, "X"), integer(value[1], 0, height - 1, "Y")]


def bounds(value, width, height):
    if not isinstance(value, list) or len(value) != 4:
        raise Invalid("Enter the four sides of the inspection box.")
    left, top = point(value[:2], width, height)
    right, bottom = point(value[2:], width, height)
    if left > right or top > bottom:
        raise Invalid("The left and top of the box must precede the right and bottom.")
    return [left, top, right, bottom]


def defaults(width, height):
    return {
        "box": [0, 0, width - 1, height - 1], "row": height // 2, "column": width // 2,
        "origin": [width // 2, height // 2], "source": "a", "threshold": 140,
        "clip_low": 10, "clip_high": 245, "radius_step": 20,
        "place_min": 120, "place_width": 200, "place_tol": 12, "place_segment": None,
    }


def segment(value, span):
    if value is None:
        return None
    if not isinstance(value, list) or len(value) != 2:
        raise Invalid("The adopted placement segment needs two profile positions.")
    start, end = value
    if isinstance(start, bool) or isinstance(end, bool) or not all(
            isinstance(item, int) for item in (start, end)):
        raise Invalid("The adopted placement segment needs whole profile positions.")
    if not 0 <= start <= end < span:
        raise Invalid("The adopted placement segment must lie inside the measured line.")
    return [start, end]


def settings(record, submitted):
    options = {**record["settings"], **document(submitted)}
    width, height = record["width"], record["height"]
    left, top, right, bottom = bounds(options["box"], width, height)
    role = options["source"]
    if not isinstance(role, str) or role not in record["sources"]:
        raise Invalid("Select an available source photo.")
    clip_low = number(options["clip_low"], 0, 254, "Shadow level")
    clip_high = number(options["clip_high"], 1, 255, "Highlight level")
    if clip_low >= clip_high:
        raise Invalid("The shadow level must be below the highlight level.")
    place_min = number(options["place_min"], 0, 255, "Minimum brightness")
    place_width = integer(options["place_width"], 1, max(width, height), "Shortest placement width")
    place_tol = number(options["place_tol"], 0, 255, "Evenness tolerance")
    span = max(right - left, bottom - top) + 1
    place_segment = segment(options.get("place_segment"), span)
    return {
        "box": [left, top, right, bottom],
        "row": integer(options["row"], top, bottom, "Profile row"),
        "column": integer(options["column"], left, right, "Profile column"),
        "origin": point(options["origin"], width, height),
        "source": role, "threshold": number(options["threshold"], 0, 255, "Light level"),
        "clip_low": clip_low, "clip_high": clip_high,
        "radius_step": integer(options["radius_step"], 4, 512, "Radial step"),
        "place_min": place_min, "place_width": place_width, "place_tol": place_tol,
        "place_segment": place_segment,
    }


def mode(value):
    if not isinstance(value, str) or value not in MODES:
        raise Invalid("Choose a lighting inspection tool.")
    return value
