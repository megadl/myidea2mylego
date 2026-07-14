"""Image → 3D LEGO model.

Two reconstruction modes, both deliberately dependency-light (the research
doc's Stage A — COLMAP / InstantMesh — plugs in here later as a mesh source):

- statue: extract the subject silhouette, extrude it to a depth, stand it up.
- relief: luminance → height map, built flat like a sculpted mosaic
  (always gravity-safe: every column is filled from the base up).

Voxel grids are indexed [layer][z][x]: layer = vertical (build) axis,
x = width, z = depth. A cell holds a palette color index, or -1 for empty.

Brick placement is the greedy larger-brick-first strategy from the research
doc (brickalize-style), with the ColouredVoxels2LDR trick of alternating the
preferred brick orientation per layer so layers interlock.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

import numpy as np
from PIL import Image

from .palette import PaletteMatcher
from .parts import BRICKS_BY_AREA, BRICK_MM, STUD_MM

EMPTY = -1


@dataclass
class PlacedBrick:
    layer: int      # 0 = bottom
    x: int          # leftmost cell (width axis)
    z: int          # nearest cell (depth axis)
    xlen: int       # extent along x
    zlen: int       # extent along z
    color: int      # palette index
    part: str       # design id
    rotated: bool   # True if the part's long axis runs along z

    def cells(self):
        for dz in range(self.zlen):
            for dx in range(self.xlen):
                yield (self.x + dx, self.z + dz)

    def as_dict(self):
        return {
            "layer": self.layer, "x": self.x, "z": self.z,
            "xlen": self.xlen, "zlen": self.zlen,
            "color": self.color, "part": self.part, "rotated": self.rotated,
        }


# ------------------------------------------------------------- foreground

def foreground_mask(img: Image.Image, grid_w: int, grid_h: int) -> tuple[np.ndarray, np.ndarray]:
    """Downsample to (grid_h, grid_w) and split subject from background.

    Uses the alpha channel when present; otherwise estimates the background
    color from the border pixels and flood-fills background-colored cells
    inward from the edges. Returns (mask bool (h,w), rgb float (h,w,3)).
    """
    img = img.convert("RGBA")
    small = img.resize((grid_w, grid_h), Image.BOX)
    arr = np.asarray(small, dtype=np.float64)
    rgb, alpha = arr[..., :3], arr[..., 3]

    if float(alpha.min()) < 128:  # image has real transparency
        mask = alpha >= 128
        return _clean_mask(mask), rgb

    border = np.concatenate([rgb[0], rgb[-1], rgb[:, 0], rgb[:, -1]])
    bg = np.median(border, axis=0)
    dist = np.linalg.norm(rgb - bg, axis=-1)
    spread = float(np.median(np.linalg.norm(border - bg, axis=-1)))
    threshold = max(40.0, spread * 3.0)
    bg_like = dist < threshold

    # Background = bg-colored cells reachable from the border.
    h, w = bg_like.shape
    background = np.zeros((h, w), dtype=bool)
    queue = deque()
    for x in range(w):
        for y in (0, h - 1):
            if bg_like[y, x] and not background[y, x]:
                background[y, x] = True
                queue.append((y, x))
    for y in range(h):
        for x in (0, w - 1):
            if bg_like[y, x] and not background[y, x]:
                background[y, x] = True
                queue.append((y, x))
    while queue:
        y, x = queue.popleft()
        for ny, nx in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)):
            if 0 <= ny < h and 0 <= nx < w and bg_like[ny, nx] and not background[ny, nx]:
                background[ny, nx] = True
                queue.append((ny, nx))

    mask = ~background
    # If nearly everything (or nothing) counts as foreground, background
    # removal failed (busy photo / uniform image) — keep the whole frame
    # and let the user crop instead.
    if mask.mean() > 0.97 or mask.mean() < 0.03:
        mask = np.ones_like(mask)
    return _clean_mask(mask), rgb


def _clean_mask(mask: np.ndarray) -> np.ndarray:
    """Drop tiny specks and fill enclosed holes so the model is printable."""
    mask = _keep_components(mask, min_cells=max(4, int(mask.size * 0.002)))
    holes = _keep_components(~mask, min_cells=0, only_touching_border=True)
    return ~holes


def _keep_components(mask: np.ndarray, min_cells: int, only_touching_border: bool = False) -> np.ndarray:
    """Connected-component filter (4-neighbor BFS on small grids)."""
    h, w = mask.shape
    seen = np.zeros((h, w), dtype=bool)
    out = np.zeros((h, w), dtype=bool)
    for sy in range(h):
        for sx in range(w):
            if not mask[sy, sx] or seen[sy, sx]:
                continue
            comp = [(sy, sx)]
            seen[sy, sx] = True
            touches_border = False
            qi = 0
            while qi < len(comp):
                y, x = comp[qi]
                qi += 1
                if y in (0, h - 1) or x in (0, w - 1):
                    touches_border = True
                for ny, nx in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)):
                    if 0 <= ny < h and 0 <= nx < w and mask[ny, nx] and not seen[ny, nx]:
                        seen[ny, nx] = True
                        comp.append((ny, nx))
            keep = len(comp) >= min_cells
            if only_touching_border:
                keep = touches_border
            if keep:
                for y, x in comp:
                    out[y, x] = True
    return out


# ------------------------------------------------------------- voxelizers

def voxelize_statue(
    img: Image.Image,
    width_studs: int,
    depth_studs: int,
    matcher: PaletteMatcher,
    max_layers: int = 160,
) -> np.ndarray:
    """Silhouette extrusion, standing upright.

    Bricks are 9.6 mm tall but studs are 8 mm apart, so the vertical stud→
    layer mapping is scaled by 8/9.6 to keep real-world proportions
    (the aspect-ratio pitfall called out in the research doc).
    """
    w, h = img.size
    layers_high = max(1, min(max_layers, round(h / w * width_studs * STUD_MM / BRICK_MM)))
    mask, rgb = foreground_mask(img, width_studs, layers_high)
    colors = matcher.match(rgb.reshape(-1, 3)).reshape(layers_high, width_studs)

    grid = np.full((layers_high, depth_studs, width_studs), EMPTY, dtype=np.int32)
    for row in range(layers_high):
        layer = layers_high - 1 - row  # image row 0 is the top of the model
        for x in range(width_studs):
            if mask[row, x]:
                grid[layer, :, x] = colors[row, x]
    return _drop_unsupported_layers(grid)


def voxelize_relief(
    img: Image.Image,
    width_studs: int,
    max_height_bricks: int,
    matcher: PaletteMatcher,
    invert: bool = False,
    max_depth_studs: int = 256,
) -> np.ndarray:
    """Luminance height map built flat: brighter → taller (or inverted).

    Every column is filled from layer 0 upward, so the result is always
    physically buildable with no floating bricks.
    """
    w, h = img.size
    depth_studs = max(1, min(max_depth_studs, round(h / w * width_studs)))
    small = img.convert("RGB").resize((width_studs, depth_studs), Image.BOX)
    rgb = np.asarray(small, dtype=np.float64)
    colors = matcher.match(rgb.reshape(-1, 3)).reshape(depth_studs, width_studs)

    lum = rgb @ np.array([0.2126, 0.7152, 0.0722])
    lo, hi = float(lum.min()), float(lum.max())
    norm = (lum - lo) / (hi - lo) if hi > lo else np.full_like(lum, 0.5)
    if invert:
        norm = 1.0 - norm
    heights = 1 + np.round(norm * (max_height_bricks - 1)).astype(np.int32)

    grid = np.full((max_height_bricks, depth_studs, width_studs), EMPTY, dtype=np.int32)
    for z in range(depth_studs):
        for x in range(width_studs):
            grid[: heights[z, x], z, x] = colors[z, x]
    return grid


def _drop_unsupported_layers(grid: np.ndarray) -> np.ndarray:
    """Trim empty layers below the model so it starts at layer 0."""
    occupied = [ly for ly in range(grid.shape[0]) if (grid[ly] != EMPTY).any()]
    if not occupied:
        return grid[:1]
    return grid[occupied[0] : occupied[-1] + 1]


def hollow(grid: np.ndarray, shell: int = 1) -> np.ndarray:
    """Remove interior voxels, keeping a `shell`-thick wall (saves bricks)."""
    g = grid.copy()
    filled = grid != EMPTY
    ly, lz, lx = grid.shape
    pad = np.zeros((ly + 2 * shell, lz + 2 * shell, lx + 2 * shell), dtype=bool)
    pad[shell:-shell, shell:-shell, shell:-shell] = filled
    interior = np.ones_like(filled)
    rng = range(-shell, shell + 1)
    for dy in rng:
        for dz in rng:
            for dx in rng:
                interior &= pad[
                    shell + dy : shell + dy + ly,
                    shell + dz : shell + dz + lz,
                    shell + dx : shell + dx + lx,
                ]
    g[interior] = EMPTY
    return g


# --------------------------------------------------------- brick placement

def place_bricks(grid: np.ndarray) -> list[PlacedBrick]:
    """Tile every filled voxel with exactly one brick (greedy, largest first).

    Even layers prefer bricks running along x, odd layers along z, so seams
    interlock between layers (stability trick from the research doc).
    """
    n_layers, lz, lx = grid.shape
    bricks: list[PlacedBrick] = []
    for layer in range(n_layers):
        cells = grid[layer]
        used = np.zeros((lz, lx), dtype=bool)
        prefer_x = layer % 2 == 0
        for z in range(lz):
            for x in range(lx):
                if cells[z, x] == EMPTY or used[z, x]:
                    continue
                color = int(cells[z, x])
                placed = None
                for part in BRICKS_BY_AREA:
                    orientations = [(part.length, part.width), (part.width, part.length)]
                    if not prefer_x:
                        orientations.reverse()
                    seen = set()
                    for xlen, zlen in orientations:
                        if (xlen, zlen) in seen:
                            continue
                        seen.add((xlen, zlen))
                        if _fits(cells, used, x, z, xlen, zlen, color):
                            # rotated: the part's long axis runs along z
                            rotated = xlen != zlen and zlen == part.length
                            placed = PlacedBrick(
                                layer, x, z, xlen, zlen, color,
                                part.design_id, rotated=rotated,
                            )
                            break
                    if placed:
                        break
                # 1×1 always fits, so `placed` is never None here.
                used[placed.z : placed.z + placed.zlen,
                     placed.x : placed.x + placed.xlen] = True
                bricks.append(placed)
    return bricks


def _fits(cells, used, x, z, xlen, zlen, color) -> bool:
    lz, lx = cells.shape
    if x + xlen > lx or z + zlen > lz:
        return False
    block_c = cells[z : z + zlen, x : x + xlen]
    block_u = used[z : z + zlen, x : x + xlen]
    return bool((block_c == color).all() and not block_u.any())


def stability_report(bricks: list[PlacedBrick]) -> dict:
    """Count bricks (above layer 0) with no stud connection to the layer below."""
    by_layer: dict[int, set] = {}
    for b in bricks:
        by_layer.setdefault(b.layer, set()).update(b.cells())
    floating = 0
    for b in bricks:
        if b.layer == 0:
            continue
        below = by_layer.get(b.layer - 1, set())
        if not any(c in below for c in b.cells()):
            floating += 1
    return {"floating_bricks": floating, "buildable": floating == 0}
