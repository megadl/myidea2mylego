"""MyIDEA2MyLEGO — image → LEGO converter web app.

POST /api/convert : multipart image + options → full build package (JSON)
GET  /api/jobs/…  : generated files (LDraw, BrickLink XML, CSV, PNGs, ZIP)
GET  /            : the app
"""

from __future__ import annotations

import io
import re
import shutil
import uuid
import zipfile
from pathlib import Path

import numpy as np
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageDraw, ImageOps

from . import exporters, instructions, mosaic, model3d
from .palette import PALETTE, PaletteMatcher, palette_subset
from .parts import BRICK_MM, PART_BY_ID, STUD_MM

ROOT = Path(__file__).resolve().parent.parent
JOBS_DIR = ROOT / "var" / "jobs"
JOBS_DIR.mkdir(parents=True, exist_ok=True)
MAX_UPLOAD_BYTES = 25 * 1024 * 1024
MAX_JOBS_KEPT = 40

app = FastAPI(title="MyIDEA2MyLEGO")


@app.get("/api/palette")
def get_palette():
    return {"colors": [c.as_dict() for c in PALETTE]}


@app.post("/api/convert")
def convert(
    file: UploadFile = File(...),
    mode: str = Form("mosaic"),          # mosaic | statue | relief
    width: int = Form(48),               # studs across
    palette_mode: str = Form("full"),    # full | classic | grayscale
    dither: bool = Form(False),
    optimize: bool = Form(True),         # merge into larger plates (mosaic)
    depth: int = Form(4),                # statue depth in studs
    relief_height: int = Form(8),        # relief max height in bricks
    invert: bool = Form(False),          # relief: dark = tall
    hollow_inside: bool = Form(True),    # statue: hollow the interior
):
    raw = file.file.read(MAX_UPLOAD_BYTES + 1)
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "Image too large (max 25 MB).")
    try:
        img = Image.open(io.BytesIO(raw))
        img.load()
        # Phone photos carry rotation in EXIF; without this, portrait
        # shots convert sideways.
        img = ImageOps.exif_transpose(img)
    except Exception:
        raise HTTPException(400, "Could not read that file as an image.")

    width = int(np.clip(width, 8, 128))
    depth = int(np.clip(depth, 1, 24))
    relief_height = int(np.clip(relief_height, 2, 20))
    if mode not in ("mosaic", "statue", "relief"):
        raise HTTPException(400, f"Unknown mode: {mode}")

    colors = palette_subset(palette_mode)
    matcher = PaletteMatcher(colors)
    job_id = uuid.uuid4().hex[:12]
    job_dir = JOBS_DIR / job_id
    job_dir.mkdir(parents=True)

    if mode == "mosaic":
        result = _convert_mosaic(img, width, matcher, dither, optimize, job_dir)
    else:
        result = _convert_3d(
            img, mode, width, matcher, depth, relief_height, invert,
            hollow_inside, job_dir,
        )

    result["job_id"] = job_id
    result["mode"] = mode
    result["palette"] = [c.as_dict() for c in colors]
    _prune_old_jobs()
    return result


def _convert_mosaic(img, width, matcher, dither, optimize, job_dir: Path):
    grid = mosaic.image_to_grid(img, width, matcher, dither=dither)
    placements = mosaic.merge_plates(grid, optimize=optimize)
    palette = matcher.colors

    bom = exporters.build_bom([(p["part"], p["color"]) for p in placements], palette)
    totals = exporters.bom_totals(bom)
    rows, cols = grid.shape

    ldr = exporters.mosaic_to_ldraw(placements, palette, "MyIDEA2MyLEGO mosaic")
    files = _write_common_files(job_dir, ldr, bom)
    _write_mosaic_chart(job_dir, grid, palette)
    files["chart"] = "mosaic_chart.png"
    files["preview"] = "mosaic_preview.png"
    _zip_job(job_dir, mode="mosaic")

    return {
        "grid": grid.tolist(),
        "placements": placements,
        "bom": bom,
        "totals": totals,
        "stats": {
            "studs_x": cols,
            "studs_z": rows,
            "size_cm": [round(cols * STUD_MM / 10, 1), round(rows * STUD_MM / 10, 1)],
            "layers": 1,
            "baseplates_32": -(-cols // 32) * -(-rows // 32),
        },
        "files": _file_urls(job_dir.name, files),
    }


def _convert_3d(img, mode, width, matcher, depth, relief_height, invert,
                hollow_inside, job_dir: Path):
    if mode == "statue":
        grid = model3d.voxelize_statue(img, width, depth, matcher)
        if hollow_inside and min(grid.shape) >= 4:
            grid = model3d.hollow(grid)
    else:
        grid = model3d.voxelize_relief(img, width, relief_height, matcher, invert=invert)

    bricks = model3d.place_bricks(grid)
    if not bricks:
        raise HTTPException(422, "No subject found in the image — try a clearer photo or a mosaic instead.")
    palette = matcher.colors
    n_layers, grid_z, grid_x = grid.shape

    bom = exporters.build_bom([(b.part, b.color) for b in bricks], palette)
    totals = exporters.bom_totals(bom)
    stability = model3d.stability_report(bricks)
    layers = exporters.layer_stats(bricks, palette)

    ldr = exporters.bricks_to_ldraw(bricks, palette, f"MyIDEA2MyLEGO {mode}")
    files = _write_common_files(job_dir, ldr, bom)

    inst_dir = job_dir / "instructions"
    inst_dir.mkdir()
    for i, im in enumerate(
        instructions.render_all_layers(bricks, grid_x, grid_z, palette)
    ):
        im.save(inst_dir / f"layer_{i + 1:03d}.png")
    _zip_job(job_dir, mode=mode)

    return {
        "bricks": [b.as_dict() for b in bricks],
        "grid_size": {"x": grid_x, "z": grid_z, "layers": n_layers},
        "bom": bom,
        "totals": totals,
        "stability": stability,
        "layer_stats": layers,
        "stats": {
            "studs_x": grid_x,
            "studs_z": grid_z,
            "layers": n_layers,
            "size_cm": [
                round(grid_x * STUD_MM / 10, 1),
                round(n_layers * BRICK_MM / 10, 1),
                round(grid_z * STUD_MM / 10, 1),
            ],
        },
        "files": _file_urls(job_dir.name, files),
    }


def _write_common_files(job_dir: Path, ldr: str, bom) -> dict:
    (job_dir / "model.ldr").write_text(ldr)
    (job_dir / "bricklink_wanted_list.xml").write_text(exporters.bricklink_xml(bom))
    (job_dir / "rebrickable.csv").write_text(exporters.rebrickable_csv(bom))
    (job_dir / "bom.csv").write_text(exporters.bom_csv(bom))
    return {
        "ldr": "model.ldr",
        "bricklink_xml": "bricklink_wanted_list.xml",
        "rebrickable_csv": "rebrickable.csv",
        "bom_csv": "bom.csv",
        "zip": "myidea2mylego.zip",
    }


def _write_mosaic_chart(job_dir: Path, grid, palette):
    """Numbered build chart + stud-style preview for mosaics."""
    rows, cols = grid.shape
    cell = 24
    used = sorted(set(int(v) for v in grid.flatten()))
    legend_h = 22 * len(used) + 16

    chart = Image.new("RGB", (cols * cell + 40, rows * cell + 60 + legend_h), (250, 248, 243))
    d = ImageDraw.Draw(chart)
    num = {color: i + 1 for i, color in enumerate(used)}
    for r in range(rows):
        for c in range(cols):
            v = int(grid[r, c])
            rgb = palette[v].rgb
            x0, y0 = 20 + c * cell, 40 + r * cell
            d.rectangle([x0, y0, x0 + cell, y0 + cell], fill=rgb, outline=(90, 88, 82))
            lum = 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]
            fg = (20, 20, 20) if lum > 128 else (240, 240, 240)
            d.text((x0 + 4, y0 + 5), str(num[v]), fill=fg)
    d.text((20, 12), "MyIDEA2MyLEGO build chart — numbers map to the legend below", fill=(60, 56, 50))
    y = rows * cell + 52
    for color, n in num.items():
        d.rectangle([20, y, 38, y + 16], fill=palette[color].rgb, outline=(90, 88, 82))
        d.text((46, y + 2), f"{n}: {palette[color].name}", fill=(60, 56, 50))
        y += 22
    chart.save(job_dir / "mosaic_chart.png")

    stud = 16
    prev = Image.new("RGB", (cols * stud, rows * stud), (30, 30, 30))
    pd = ImageDraw.Draw(prev)
    for r in range(rows):
        for c in range(cols):
            rgb = palette[int(grid[r, c])].rgb
            x0, y0 = c * stud, r * stud
            pd.rectangle([x0, y0, x0 + stud, y0 + stud], fill=rgb)
            hi = tuple(min(255, int(v * 1.25)) for v in rgb)
            lo = tuple(int(v * 0.8) for v in rgb)
            pd.ellipse([x0 + 3, y0 + 3, x0 + stud - 3, y0 + stud - 3], outline=lo, width=1)
            pd.arc([x0 + 3, y0 + 3, x0 + stud - 3, y0 + stud - 3], 180, 300, fill=hi, width=1)
    prev.save(job_dir / "mosaic_preview.png")


_ZIP_README = """MyIDEA2MyLEGO — your build package
==================================

Files:
- model.ldr                  Open in LeoCAD / LDView / LPub3D / BrickLink Studio
                             (each build layer is one STEP).
- bricklink_wanted_list.xml  Upload at bricklink.com > Want > Upload
                             (Upload BrickLink XML format) to buy every part.
- rebrickable.csv            Import at rebrickable.com/users/<you>/partlists/
- bom.csv                    Full bill of materials with color IDs & estimates.
- instructions/ (3D)         One top-down PNG per build layer; gray = layer below.
- mosaic_chart.png (mosaic)  Numbered placement chart with a color legend.

Where to buy:
- BrickLink   https://www.bricklink.com/v2/wanted/upload.page
- LEGO Pick a Brick  https://www.lego.com/en-us/pick-and-build/pick-a-brick
  (search by design ID, e.g. 3024)
- Rebrickable https://rebrickable.com (finds sets that contain your parts)

Prices in bom.csv are rough BrickLink new-part averages — actual prices vary
by color and seller. Have fun building!
"""


def _zip_job(job_dir: Path, mode: str):
    (job_dir / "README.txt").write_text(_ZIP_README)
    zpath = job_dir / "myidea2mylego.zip"
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(job_dir.rglob("*")):
            if f.is_file() and f != zpath:
                z.write(f, f.relative_to(job_dir))


def _file_urls(job_id: str, files: dict) -> dict:
    return {k: f"/api/jobs/{job_id}/{v}" for k, v in files.items()}


_JOB_ID_RE = re.compile(r"^[0-9a-f]{12}$")


@app.get("/api/jobs/{job_id}/{path:path}")
def get_job_file(job_id: str, path: str):
    if not _JOB_ID_RE.fullmatch(job_id):
        raise HTTPException(404, "Not found")
    base = (JOBS_DIR / job_id).resolve()
    target = (base / path).resolve()
    if not target.is_relative_to(base) or not target.is_file():
        raise HTTPException(404, "Not found")
    return FileResponse(target)


def _prune_old_jobs():
    # Concurrent requests may prune simultaneously; tolerate directories
    # vanishing between listing and stat/removal.
    jobs = []
    try:
        for p in JOBS_DIR.iterdir():
            try:
                jobs.append((p.stat().st_mtime, p))
            except FileNotFoundError:
                continue
    except OSError:
        return
    jobs.sort()
    while len(jobs) > MAX_JOBS_KEPT:
        shutil.rmtree(jobs.pop(0)[1], ignore_errors=True)


app.mount("/", StaticFiles(directory=ROOT / "static", html=True), name="static")
