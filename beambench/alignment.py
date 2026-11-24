"""Suggest a horizontal shift between the two photos from shared desk texture."""

import cv2
import numpy as np

from .frame import luma

SUPPORT_NCC = 0.45   # patch correlation needed to back a shift
MIN_MEAN_NCC = 0.5   # mean correlation required across the backing patches
TEXTURE_FLOOR = 0.4  # minimum patch texture standard deviation (luma units)
SPOT_LEVEL = 6.0     # smooth light-field change (luma) that starts to discount a patch


def suggest(main_rgb, reference_rgb, box, max_shift=None):
    """Recommend the horizontal pixel offset of the reference photo relative to the main photo.

    Only desk texture recognizable in both photos backs the recommendation: the smooth
    light field is removed before matching, and patches where that field changed (a moved
    light spot) are discounted so the lamp cannot align the photos by itself. When slight
    perspective makes one marker match sharply but only locally, the shift backed by the
    broadest set of patches wins instead. The returned marks locate the backing patches in
    original photo coordinates.
    """
    left, top, right, bottom = box
    main = luma(main_rgb)[top:bottom + 1, left:right + 1].astype(np.float32)
    reference = luma(reference_rgb)[top:bottom + 1, left:right + 1].astype(np.float32)
    height, width = main.shape
    if max_shift is None:
        max_shift = min(96, max(8, width // 3))
    max_shift = max(0, min(int(max_shift), width - 8))
    sigma = max(4.0, min(width, height) / 28)
    smooth_main = cv2.GaussianBlur(main, (0, 0), sigma)
    smooth_reference = cv2.GaussianBlur(reference, (0, 0), sigma)
    texture_main = main - smooth_main
    texture_reference = reference - smooth_reference
    spot_change = np.abs(smooth_main - smooth_reference)

    patch = int(np.clip(round(min(width, height) / 6), 24, 96))
    shifts = np.arange(-max_shift, max_shift + 1)
    support = np.zeros(shifts.size)
    quality = np.zeros(shifts.size)
    patches = []
    for py in range(0, height - patch + 1, patch):
        for px in range(0, width - patch + 1, patch):
            template = texture_main[py:py + patch, px:px + patch]
            if float(template.std()) < TEXTURE_FLOOR:
                continue
            x0, x1 = max(0, px - max_shift), min(width, px + patch + max_shift)
            band = texture_reference[py:py + patch, x0:x1]
            if float(band.std()) < TEXTURE_FLOOR:
                continue
            scores = cv2.matchTemplate(band, template, cv2.TM_CCOEFF_NORMED)[0]
            ncc = np.full(shifts.size, np.nan)
            offsets = x0 + np.arange(scores.size) - px
            ncc[offsets + max_shift] = scores
            change = float(spot_change[py:py + patch, px:px + patch].mean())
            weight = 1.0 if change <= SPOT_LEVEL else 1.0 / (1.0 + (change - SPOT_LEVEL) / 10.0)
            patches.append({"x": px, "y": py, "size": patch, "weight": weight, "ncc": ncc})

    for entry in patches:
        ncc = entry["ncc"]
        support += np.where(ncc >= SUPPORT_NCC, entry["weight"], 0.0)
        quality += entry["weight"] * np.nan_to_num(np.maximum(ncc, 0.0))
    order = sorted(range(shifts.size), key=lambda i: (support[i], quality[i]), reverse=True)
    best = order[0]
    shift_x = int(shifts[best])
    supporters = [entry for entry in patches if entry["ncc"][best] >= SUPPORT_NCC]
    mean_ncc = float(np.mean([entry["ncc"][best] for entry in supporters])) if supporters else 0.0
    own = [int(shifts[int(np.nanargmax(entry["ncc"]))]) for entry in supporters]
    spread = [min(own), max(own)] if own else None
    peak_shift = 0
    if patches:
        sharpest = max(patches, key=lambda entry: np.nanmax(entry["ncc"]))
        peak_shift = int(shifts[int(np.nanargmax(sharpest["ncc"]))])

    total_weight = sum(entry["weight"] for entry in patches)
    reliable = bool(
        len(patches) >= 6
        and support[best] >= max(3.0, 0.35 * total_weight)
        and mean_ncc >= MIN_MEAN_NCC
        and width - abs(shift_x) >= width * 0.5
    )
    marks = [{"kind": "support",
              "center": [left + entry["x"] + entry["size"] // 2, top + entry["y"] + entry["size"] // 2]}
             for entry in supporters] if reliable else []

    if not patches:
        note = "No shared desk texture inside the inspection box; keeping the unshifted comparison."
    elif not reliable:
        note = (f"Common texture is too weak ({len(supporters)} of {len(patches)} textured patches "
                f"agree); keeping the unshifted comparison.")
    else:
        note = f"Shift {shift_x:+d} px is backed by {len(supporters)} of {len(patches)} textured patches (marked)."
        if peak_shift != shift_x:
            note += (f" The sharpest single marker prefers {peak_shift:+d} px but fewer patches back it;"
                     " the suggestion favors the broader match.")
        if spread and spread[0] != spread[1]:
            note += (f" Patch-level shifts span {spread[0]:+d}…{spread[1]:+d} px (slight perspective);"
                     " the suggestion is the compromise.")

    return {
        "shift_x": shift_x if reliable else 0,
        "reliable": reliable,
        "usable_patches": len(patches),
        "supporting": len(supporters),
        "mean_ncc": round(mean_ncc, 3),
        "spread": spread,
        "marks": marks,
        "candidates": [{"shift_x": int(shifts[i]), "support": round(float(support[i]), 2),
                        "quality": round(float(quality[i]), 2)} for i in order[:5]],
        "note": note,
    }
