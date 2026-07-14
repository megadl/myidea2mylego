"""Server-rendered build-instruction PNGs (one top-down image per layer)."""

from __future__ import annotations

from PIL import Image, ImageDraw

from .model3d import PlacedBrick
from .palette import LegoColor

CELL = 26
MARGIN = 20
HEADER = 34


def _shade(rgb: tuple, f: float) -> tuple:
    return tuple(max(0, min(255, int(c * f))) for c in rgb)


def render_layer(
    bricks: list[PlacedBrick],
    layer: int,
    grid_x: int,
    grid_z: int,
    palette: list[LegoColor],
    total_layers: int,
) -> Image.Image:
    w = grid_x * CELL + 2 * MARGIN
    h = grid_z * CELL + 2 * MARGIN + HEADER
    img = Image.new("RGB", (w, h), (248, 246, 240))
    d = ImageDraw.Draw(img)

    layer_bricks = [b for b in bricks if b.layer == layer]
    below = [b for b in bricks if b.layer == layer - 1]

    def cell_rect(x, z, xlen=1, zlen=1):
        x0 = MARGIN + x * CELL
        y0 = HEADER + MARGIN + z * CELL
        return [x0, y0, x0 + xlen * CELL, y0 + zlen * CELL]

    # Ghost of the layer below, so builders can align.
    for b in below:
        d.rectangle(cell_rect(b.x, b.z, b.xlen, b.zlen), fill=(224, 221, 212))

    # Grid.
    for gx in range(grid_x + 1):
        x = MARGIN + gx * CELL
        d.line([(x, HEADER + MARGIN), (x, HEADER + MARGIN + grid_z * CELL)], fill=(230, 228, 220))
    for gz in range(grid_z + 1):
        y = HEADER + MARGIN + gz * CELL
        d.line([(MARGIN, y), (MARGIN + grid_x * CELL, y)], fill=(230, 228, 220))

    # This layer's bricks with studs.
    for b in layer_bricks:
        rgb = palette[b.color].rgb
        rect = cell_rect(b.x, b.z, b.xlen, b.zlen)
        d.rectangle(rect, fill=rgb, outline=_shade(rgb, 0.55), width=2)
        for cx, cz in b.cells():
            r = cell_rect(cx, cz)
            pad = CELL * 0.22
            d.ellipse(
                [r[0] + pad, r[1] + pad, r[2] - pad, r[3] - pad],
                outline=_shade(rgb, 0.7),
                width=2,
            )

    d.text(
        (MARGIN, 10),
        f"Layer {layer + 1} / {total_layers}   ({len(layer_bricks)} pieces)",
        fill=(60, 56, 50),
    )
    return img


def render_all_layers(bricks, grid_x, grid_z, palette) -> list[Image.Image]:
    total = max((b.layer for b in bricks), default=0) + 1
    return [
        render_layer(bricks, ly, grid_x, grid_z, palette, total)
        for ly in range(total)
    ]
