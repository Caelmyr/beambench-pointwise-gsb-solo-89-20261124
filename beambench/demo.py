"""Make aligned, procedurally drawn tabletop illumination test photos."""

import numpy as np
from PIL import Image, ImageDraw

from .model import defaults


def photo(reference=False):
    width, height = 980, 670
    y, x = np.mgrid[:height, :width]
    normalizer = ((x - 463) / 325) ** 2 + ((y - 315) / 200) ** 2
    value = 34 + 143 * np.exp(-normalizer ** 1.75)
    value += 34 * np.exp(-(((x - 338) / 132) ** 2 + ((y - 260) / 107) ** 2))
    value += 19 * np.exp(-(((x - 710) / 82) ** 2 + ((y - 385) / 89) ** 2))
    value -= 23 * np.exp(-((x - 515) / 28) ** 2) * np.exp(-((y - 335) / 97) ** 2)
    value += 0.8 * np.sin(x / 11 + y / 15)
    if reference:
        value = 8 + 0.87 * value + 18 * np.exp(-(((x - 687) / 96) ** 2 + ((y - 283) / 130) ** 2))
    warmth = 27 * np.exp(-(((x - 352) / 265) ** 2 + ((y - 263) / 260) ** 2))
    rgb = np.stack([value + warmth, value + warmth * 0.42, value - warmth * 0.47], axis=-1)
    image = Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8))
    draw = ImageDraw.Draw(image)
    for corner_x in (62, width - 62):
        for corner_y in (63, height - 63):
            draw.line((corner_x - 10, corner_y, corner_x + 10, corner_y), fill=(119, 116, 118), width=1)
            draw.line((corner_x, corner_y - 10, corner_x, corner_y + 10), fill=(119, 116, 118), width=1)
    for index, value in enumerate((34, 66, 104, 147, 193, 239)):
        start = width // 2 - 124 + index * 42
        draw.rectangle((start, height - 53, start + 35, height - 40), fill=(value, value, value))
    return image


def create(library):
    main = photo()
    options = {
        **defaults(*main.size), "box": [74, 82, 905, 565], "row": 318, "column": 462,
        "origin": [397, 307], "threshold": 114,
    }
    return library.create("Softbox · tabletop sweep", {
        "a": (main, "Synthetic key light.png"),
        "b": (photo(reference=True), "Synthetic fill light.png"),
    }, options, synthetic=True)
