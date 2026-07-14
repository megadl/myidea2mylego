# MyIDEA2MyLEGO 🧱

**A paradise of LEGO dreams.** Drop in any picture and get back everything you
need to build it for real: an interactive brick preview, layer-by-layer build
instructions, a full Bill of Materials in real LEGO colors, price & weight
estimates, and one-click shopping files for BrickLink, LEGO Pick a Brick and
Rebrickable.

## Quick start

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn server.main:app --port 8318
# open http://localhost:8318
```

## What it does

| Mode | What you get |
|---|---|
| **Mosaic** | Flat wall art from 1×N plates, CIEDE2000 color matching, optional Floyd–Steinberg dithering, greedy merging into large plates (fewer pieces, lower cost), numbered printable build chart. |
| **3D Statue** | Automatic subject cut-out (alpha channel or background flood-fill), extruded into a standing model, optional hollowing, interlocked greedy brick layout, floating-brick stability check. |
| **3D Relief** | Brightness → height sculpture, always gravity-safe, adjustable height and inversion. |

Every conversion produces:

- `model.ldr` — LDraw file with one `STEP` per build layer. Opens in LeoCAD,
  LDView, LPub3D, BrickLink Studio for photoreal renders & print instructions.
- `bricklink_wanted_list.xml` — upload at *BrickLink → Want → Upload* to buy
  every part in one go.
- `rebrickable.csv` — import into Rebrickable to check parts you already own.
- `bom.csv` — full parts list with BrickLink / LDraw / LEGO color IDs.
- `instructions/layer_*.png` (3D) or `mosaic_chart.png` (mosaic) — printable
  step-by-step instructions.
- Per-layer statistics (pieces per layer, per part+color) in the UI.

## How it works (and where it came from)

This implements the pipeline recommended in the bundled research document
(`compass_artifact_…markdown.md`), optimized for a zero-setup local tool:

1. **Image → grid/voxels** — instead of heavyweight photogrammetry, the app
   ships two dependency-free reconstructions (silhouette extrusion and
   luminance relief) plus flat mosaics. The vertical axis is scaled by
   8 mm/9.6 mm (stud pitch vs brick height) to avoid the classic
   "stretched model" pitfall.
2. **Color matching** — CIEDE2000 in Lab space (Sharma et al. 2005,
   validated against the paper's test pairs) against a 40-color palette of
   real LEGO solids with LDraw + BrickLink + LEGO ID mappings.
3. **Voxels → bricks** — greedy largest-brick-first tiling with per-layer
   alternating orientation so layers interlock (the ColouredVoxels2LDR
   stability trick), optional shell hollowing, and a floating-brick check.
4. **Exports** — LDraw type-1 lines (20 LDU stud pitch / 24 LDU brick,
   `0 STEP` per layer), BrickLink Wanted List XML, Rebrickable CSV, and a
   per-layer BoM derived exactly as the research doc describes.

### Roadmap

**Next planned feature — 3D Scene mode** (photo → monocular depth → parallax
diorama / bas-relief): see [docs/PLAN-3d-scene.md](docs/PLAN-3d-scene.md) for
the full design (algorithm candidates, app changes, milestones).

### Upgrade path (from the research doc)

The reconstruction stage is intentionally pluggable. To go from "one photo"
to "true multi-view 3D", feed a mesh from **COLMAP / Meshroom** (many photos)
or **InstantMesh / TripoSR** (one clean shot) into a voxelizer and hand the
`[layer][z][x]` color grid to `model3d.place_bricks()` — everything downstream
(LDraw, BoM, instructions, shopping files) already works.

## Project layout

```
server/
  palette.py       LEGO colors + CIEDE2000 matching
  parts.py         part catalog (plates & bricks, prices, weights)
  mosaic.py        image → stud grid → merged plate placements
  model3d.py       image → voxels → placed bricks (+ stability report)
  exporters.py     LDraw / BrickLink XML / Rebrickable CSV / BoM / layer stats
  instructions.py  per-layer instruction PNGs
  main.py          FastAPI app + job packaging (ZIP)
static/            self-contained frontend (no CDN)
tests/             unit tests (CIEDE2000 reference pairs, invariants)
```

## Tests

```bash
.venv/bin/pytest
```

## License

Licensed under the [Apache License 2.0](LICENSE).

*LEGO® is a trademark of the LEGO Group, which does not sponsor, authorize or
endorse this project. Prices are rough estimates; check sellers for real ones.*
