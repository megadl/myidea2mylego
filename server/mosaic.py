"""Image → LEGO mosaic: stud grid, optional dithering, greedy plate merging."""

from __future__ import annotations

import numpy as np
from PIL import Image

from .palette import LegoColor, PaletteMatcher, ciede2000, srgb_to_lab
from .parts import PLATE_1X1, PLATES_BY_AREA


def image_to_grid(
    img: Image.Image,
    width_studs: int,
    matcher: PaletteMatcher,
    dither: bool = False,
    max_height_studs: int = 256,
) -> np.ndarray:
    """Resample the image to a stud grid and match every stud to a LEGO color.

    Returns an int array (rows, cols) of palette indices into matcher.colors.
    Mosaics are flat, so studs are square — no aspect-ratio correction here.
    """
    img = img.convert("RGBA")
    w, h = img.size
    height_studs = max(1, min(max_height_studs, round(h / w * width_studs)))
    img = img.resize((width_studs, height_studs), Image.BOX)

    # Composite transparency onto white so PNG logos behave predictably.
    bg = Image.new("RGBA", img.size, (255, 255, 255, 255))
    rgb = np.asarray(Image.alpha_composite(bg, img).convert("RGB"), dtype=np.float64)

    if not dither:
        idx = matcher.match(rgb.reshape(-1, 3))
        return idx.reshape(height_studs, width_studs)

    return _floyd_steinberg(rgb, matcher)


def _floyd_steinberg(rgb: np.ndarray, matcher: PaletteMatcher) -> np.ndarray:
    """Error-diffusion dithering with CIEDE2000 nearest-color selection."""
    h, w, _ = rgb.shape
    work = rgb.copy()
    out = np.zeros((h, w), dtype=np.int32)
    pal_rgb = matcher._rgb
    pal_lab = matcher._lab
    for y in range(h):
        for x in range(w):
            px = np.clip(work[y, x], 0, 255)
            d = ciede2000(srgb_to_lab(px[None, :]), pal_lab)[0]
            k = int(np.argmin(d))
            out[y, x] = k
            err = px - pal_rgb[k]
            if x + 1 < w:
                work[y, x + 1] += err * (7 / 16)
            if y + 1 < h:
                if x > 0:
                    work[y + 1, x - 1] += err * (3 / 16)
                work[y + 1, x] += err * (5 / 16)
                if x + 1 < w:
                    work[y + 1, x + 1] += err * (1 / 16)
    return out


def merge_plates(grid: np.ndarray, optimize: bool = True) -> list[dict]:
    """Convert a stud grid into plate placements.

    optimize=True merges horizontal runs of same-colored studs into the
    largest available 1×N plates (greedy, longest first), alternating scan
    direction per row so seams stagger. optimize=False emits 1×1 plates only.

    Placement dict: {row, col, length, color, part} — col is the leftmost stud.
    """
    rows, cols = grid.shape
    placements: list[dict] = []
    if not optimize:
        for r in range(rows):
            for c in range(cols):
                placements.append(
                    {"row": r, "col": c, "length": 1,
                     "color": int(grid[r, c]), "part": PLATE_1X1.design_id}
                )
        return placements

    lengths = [p.length for p in PLATES_BY_AREA]  # [8, 6, 4, 3, 2, 1]
    for r in range(rows):
        runs = []
        start = 0
        for c in range(1, cols + 1):
            if c == cols or grid[r, c] != grid[r, start]:
                runs.append((start, c - start, int(grid[r, start])))
                start = c
        for run_start, run_len, color in runs:
            pieces = _split_run(run_len, lengths)
            if r % 2 == 1:
                pieces = pieces[::-1]  # stagger seams on odd rows
            c = run_start
            for piece_len in pieces:
                part = next(p for p in PLATES_BY_AREA if p.length == piece_len)
                placements.append(
                    {"row": r, "col": c, "length": piece_len,
                     "color": color, "part": part.design_id}
                )
                c += piece_len
    return placements


def _split_run(n: int, lengths: list[int]) -> list[int]:
    """Split a run of n studs into available plate lengths, longest first."""
    out = []
    for L in lengths:
        while n >= L:
            out.append(L)
            n -= L
    return out
