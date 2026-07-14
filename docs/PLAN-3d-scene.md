# Plan: 2D Image → 3D LEGO Scene via Monocular Depth

**Status:** approved-for-planning draft · **Target:** MyIDEA2MyLEGO v2 "Scene mode"
**Reference test image:** user's forest-path-by-lake photo (dense canopy, receding
path, water reflections — deliberately hard; if the pipeline handles it well,
typical photos are easy).

---

## 1. Goal

Add a **3D Scene** capability: the user uploads one ordinary photo, the app runs
monocular depth estimation locally, and converts image + depth into a buildable
LEGO 3D scene — with the same deliverables the app already produces (interactive
preview, per-layer instructions, BoM, BrickLink/Rebrickable files, LDraw export,
price/weight, stability report).

Two complementary scene styles (both from the same depth map):

| Style | What it is | Best for |
|---|---|---|
| **A. Parallax diorama** | Depth quantized into K vertical cut-out panels standing at increasing distance on a base — a "theater flat" shadow-box | Display pieces; strongest 3D effect from the front; modest piece count |
| **B. Bas-relief** | Continuous per-pixel protrusion from a back plane (wall-art that bulges toward the viewer), or the same laid flat as a height-field terrain | Faithful geometry; simpler construction; always buildable when flat |

---

## 2. Monocular depth: algorithm candidates

### 2.1 Candidates compared

| Model | Output | Quality | Speed (M-series Mac) | Weights / license | Size | Notes |
|---|---|---|---|---|---|---|
| **Depth Anything V2 – Small** ⭐ | relative (inverse) depth | very good, sharp edges | ~0.2–1 s @518² (ONNX CPU); ~30–50 ms via Core ML/ANE | **Apache-2.0** | ~25 M params, 50–100 MB | The pragmatic default. Mature ONNX + Core ML ports; HF `transformers` support |
| Depth Anything V2 – Base/Large | relative | better | slower | **CC-BY-NC-4.0** ⚠ | 97 M / 335 M | Non-commercial license — do not ship as default |
| Depth Anything V2 – Metric (In/Outdoor) | **metric** | good | ~Small/Base | mirrors size license | — | Outdoor variant relevant for landscapes |
| **Depth Pro (Apple)** | **metric + focal estimate** | best boundaries (foliage, hair) | a few seconds on MPS | Apple's own license — **review before any commercial use** | ~1.9 GB ckpt | Optional "quality" backend; native on this Mac via PyTorch-MPS |
| Depth Anything 3 (late 2025) | relative/any-view | strong; multi-view capable | TBD | verify per-size licensing at implementation time | — | Evaluate when tooling (ONNX/CoreML ports) matures; also unlocks future multi-photo scenes |
| MiDaS v3.1 (small) | relative | decent (dated) | fast | **MIT** | ~80 MB | Pure-MIT fallback if license maximalism is required |
| Marigold (diffusion) | relative | excellent fine detail | tens of seconds+ | Apache-2.0 (model card) | SD-based, heavy | Overkill; wrong latency class for an interactive app |
| ZoeDepth | metric | superseded | medium | MIT | ~1.4 GB | Only of historical interest now |
| UniDepth v2 / Metric3D v2 | metric (+intrinsics/normals) | strong | heavy | CC-BY-NC / verify | large | Research-grade; licensing and weight make them poor fits |

⭐ = recommended default.

### 2.2 Recommendation

- **Default backend: Depth Anything V2 Small via ONNX Runtime.**
  Apache-2.0 end to end, ~120 MB total footprint (onnxruntime wheel ≈ 15–20 MB +
  model ≈ 100 MB fp32 / 50 MB fp16), no PyTorch dependency, 0.2–1 s per image on
  this machine — fast enough to feel interactive, robust on outdoor scenes.
- **Optional "quality/metric" backend: Depth Pro** (PyTorch + MPS). Gives metric
  depth + estimated focal length → correct real-world proportions and the best
  edge fidelity on foliage. Installed on demand (`requirements-depth-pro.txt`);
  the UI shows it only when importable.
- **Escape hatch: user-supplied depth map upload** (grayscale PNG/EXR, near=bright).
  Zero-dependency path; also makes automated tests independent of any model.
- Optional micro-optimization for Macs later: Apple's Core ML port of DA-V2-Small
  (Apache-2.0, ~50 MB, runs on the Neural Engine) behind the same interface.

### 2.3 Why relative depth is acceptable (and what metric buys)

We quantize depth into at most ~10–20 LEGO planes/protrusion steps, so
affine-invariant (relative) depth is sufficient for both styles. Metric depth
(Depth Pro) additionally allows: labeling planes with real distances ("path
bend ≈ 6 m"), plausible inter-panel spacing, and consistent scale across
multiple scenes. Design the interface so `metric: bool` and `focal_px` ride
along when available, but nothing downstream requires them.

### 2.4 Depth post-processing pipeline (critical for LEGO quality)

Raw model output → buildable depth, in order:

1. **Normalize** to nearness `d ∈ [0,1]` using robust percentiles (2 % / 98 %)
   — DA-V2/MiDaS emit disparity-like maps (near = large); Depth Pro emits meters
   (invert to nearness). Percentile clipping kills outlier spikes from
   reflections.
2. **Edge-aware smoothing:** 3×3 median (despeckle) + guided filter with the RGB
   image as guidance (keeps tree-trunk silhouettes crisp while flattening leaf
   noise). Both are ~30 lines of numpy; no new deps.
3. **Water/sky clamping (scene heuristics):**
   - *Water:* mirror-like regions confuse depth nets (the lake will read partly
     as "distant trees"). Heuristic v1: user toggle "flatten water" + detect
     low-texture, high-saturation-blue/green regions in the lower half touching
     the image border; clamp their nearness to the row-wise minimum (treat as
     ground plane receding). Keep conservative; always user-overridable.
   - *Sky:* clamp top-connected very-far regions to the far plane (not relevant
     for the reference image — full canopy — but common elsewhere).
4. **Downsample to stud grid with `Image.BOX`-equivalent area averaging** (same
   lesson as color: no ringing), *after* smoothing, so panel masks are stable.
5. **Buildability gradient clamp (style B only):** limit protrusion change
   between vertically adjacent rows to ≤ 2 studs so upright reliefs never
   produce unsupported cliffs.

---

## 3. Depth → LEGO scene construction

### 3.1 Style A — Parallax diorama (`mode=diorama`)

Algorithm:

1. Compute nearness map `d` at stud resolution (W × H_studs, vertical rows scaled
   by 8/9.6 as in statue mode).
2. **Quantize into K planes** (default K=6, range 3–12): k-means on `d` (1-D)
   with ordered centroids; uniform-in-disparity fallback. Uniform disparity ≈
   perceptually even parallax steps, and k-means adapts to bimodal scenes like
   "path vs far shore".
3. **Cleanup per plane mask:** minimum blob size (reuse `_keep_components`),
   morphological close, and reassignment of orphaned specks to the neighboring
   plane with the closest centroid. Target: no 1-stud confetti panels.
4. **Perspective compensation (the theater-flat trick):** scale plane *i*'s
   content by `(V + z_i) / V` where `z_i` is its physical distance from the
   front plane and `V` the design viewing distance (default 3× scene width).
   From the intended viewpoint the panels re-compose the original image exactly;
   without this, far panels look shrunken.
5. **Emit voxels** into the existing `[layer][z][x]` grid: each plane is a
   vertical panel (default 1 stud thick; 2-stud "sturdy" option) at
   `z = i × spacing` (spacing default 3 studs, range 1–4); colors from the
   already-matched mosaic of that plane's pixels.
6. **Base & bracing:** a 1-brick-high base slab spanning the full footprint
   (+1 stud margin); every panel's bottom row sits on it (real stud
   connections). Panels taller than ~15 layers get rear buttress columns every
   ~8 studs (simple deterministic rule; `stability_report` validates the
   result).
7. **Occlusion honesty:** pixels hidden behind nearer panels don't exist on
   farther panels — perfect from the front, gappy from the side. v1 documents
   this; v2 stretch: dilate far-plane masks a few studs behind occluders with
   nearest-color fill for nicer off-axis views.

Depth budget example: 48-stud-wide scene, K=6, spacing 3 → ~38 cm × ~29 cm ×
~15 cm diorama.

### 3.2 Style B — Bas-relief (`mode=depth_relief`)

- **Flat variant (default, always buildable):** identical machinery to today's
  relief mode but height = **depth** instead of luminance. Every column fills
  from the base → zero floating bricks by construction. This is the cheapest
  win in the whole plan (~20 lines: pass a height-source array into the
  existing `voxelize_relief` core).
- **Upright variant (wall art):** per-column protrusion from a back plane,
  `p = 1 + round(d × (D_max − 1))`, standing vertically like statue mode
  (8/9.6 row scaling, gradient clamp from §2.4-5, existing stability warning
  for residual overhangs). Back plane 1 stud thick guarantees a connected
  substrate.

### 3.3 Shared

Everything downstream already exists and needs **zero changes**: greedy brick
placement with per-layer interlock, LDraw export (chirality already fixed —
diorama z maps to −z), instruction PNGs, layered BoM, pricing, BrickLink XML,
Rebrickable CSV, ZIP packaging, stability report.

---

## 4. Application changes

### 4.1 New backend modules

```
server/depth.py        # estimator interface + backends + model management
server/scene3d.py      # quantization, diorama builder, depth-relief builder
```

`depth.py` design:

```python
class DepthResult:  depth: np.ndarray  # (H,W) float32 nearness in [0,1]
                    metric: bool; focal_px: float | None; backend: str

class DepthBackend(Protocol):
    name: str
    def available(self) -> bool          # importable + weights present?
    def estimate(self, img: Image) -> DepthResult

BACKENDS = [DepthAnythingV2Onnx(), DepthProTorch(), UploadedDepth(), MidasOnnx()]
```

- **Model management:** lazy download on first use to `var/models/` with SHA-256
  verification and a progress callback; thread-safe singleton load; clear
  offline error ("run `python -m server.depth fetch` or upload a depth map").
- **Depth caching:** key = SHA-256 of image bytes + backend name → cache
  `depth.npy` in `var/depthcache/`. Re-tuning plane count / spacing / style then
  skips inference entirely — this is the single biggest UX lever, since
  inference is the only slow step.

### 4.2 API changes (`server/main.py`)

- `POST /api/convert` gains modes `diorama`, `depth_relief` and fields:
  `depth_backend` (auto|dav2|depthpro|upload), `k_planes`, `plane_spacing`,
  `panel_thick`, `max_protrusion`, `relief_lay` (flat|upright), `flatten_water`,
  `perspective_comp`, optional second file `depth_file`.
- New `GET /api/depth/status` → which backends are available/downloaded (drives
  UI affordances), and `POST /api/depth/preview` → `{job-scoped depth.png}`
  heatmap for pre-build tuning.
- Response additions: `depth_png` URL, `planes: [{index, z_studs, share_pct,
  mean_distance?}]` for the UI legend; job ZIP gains `depth.png` + `scene.json`.
- Keep the endpoint sync (post-cache conversions stay < 2 s); first-ever call
  per backend may take seconds-to-minutes (download) → the status endpoint +
  frontend messaging covers it.

### 4.3 Frontend

- New mode card **🏞️ 3D Scene** with a style toggle (Diorama / Relief-flat /
  Relief-wall) and controls: depth planes K slider, spacing, protrusion depth,
  sturdy-panels checkbox, flatten-water checkbox, backend picker (shown only
  when >1 available), "upload my own depth map" input.
- **Depth preview panel:** after image selection, a "Preview depth" button
  renders the heatmap beside the photo (canvas, client-side colormap) with the
  K quantization bands overlaid as contour tints — tune before committing to a
  build.
- Preview/instructions/BoM tabs work as-is (the iso renderer and layer viewer
  are geometry-agnostic). Nice-to-have: in diorama results, color-code the
  plane legend and add a "top view" toggle to visualize panel spacing.

### 4.4 Packaging & config

- `requirements.txt` unchanged (core stays light).
  `requirements-depth.txt`: `onnxruntime`, `huggingface_hub` (or plain URL
  download). `requirements-depth-pro.txt`: `torch`, `depth_pro` package.
- Feature-detect at startup; `/api/depth/status` reflects reality; README gains
  an install matrix. New `THIRD_PARTY.md` with model licenses/attributions.

---

## 5. Performance targets (this machine: Apple-Silicon Mac)

| Step | Target |
|---|---|
| DA-V2-Small inference @518² | ≤ 1 s (ONNX CPU) · ~50 ms if Core ML backend added |
| Depth post-processing + quantization | ≤ 150 ms |
| Voxelize + place bricks (48–96 studs) | ≤ 1 s (existing code, unchanged) |
| Re-tune with cached depth | ≤ 2 s end-to-end |
| One-time model download | ~100 MB, progress surfaced in UI |
| Peak added RAM | ≤ 500 MB during inference |

---

## 6. Testing & verification

1. **Unit (no model needed):** synthetic depth fields (linear ramp, step edge,
   noisy plateau) → assert quantization mask properties, plane ordering, min
   blob enforcement, perspective-comp scaling math, gradient clamp; diorama
   voxel invariants (exact cover, panels at declared z, every panel bottom row
   on base); flat depth-relief must always pass `stability_report`.
2. **Mock backend:** `UploadedDepth` doubles as the test backend — CI runs the
   whole convert path with a checked-in 64×64 depth PNG. No downloads in CI.
3. **Opt-in integration tests** (`pytest -m depth`): run the real DA-V2-Small on
   two fixture photos; assert statistical sanity (near/far ordering along the
   path axis, no NaNs, edge alignment vs RGB gradients ≥ threshold), not pixel
   equality.
4. **E2E in browser:** upload reference image → preview depth → build diorama →
   verify panel count, downloads, LDraw z-ordering (front panel nearest z=0,
   all z ≤ 0 in file), and instruction pages showing per-panel rows.
5. **Physical sanity review:** open generated `.ldr` in LeoCAD; check panels
   stand, base connects, buttress rule triggers on tall panels.

---

## 7. Risks & mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Foliage/thin branches → mushy depth | noisy panel assignment in canopy | median+guided filter (§2.4), min-blob merge, fewer planes by default |
| Water reflections read as far geometry | lake becomes a "hole" | flatten-water heuristic + user toggle; depth preview makes it visible pre-build |
| Relative-depth scale ambiguity | odd proportions between scenes | uniform-in-disparity quantization; optional Depth Pro metric backend |
| Panel wobble (1-stud walls) | display fragility | 2-stud sturdy option, buttress rule, base margin; stability report stays honest |
| Model download friction | first-run stall | status endpoint + UI progress, cached forever, uploadable depth as fallback |
| License creep (NC-licensed models) | legal exposure if shipped | default stack 100 % Apache-2.0/MIT; NC/custom models opt-in and documented in THIRD_PARTY.md |
| Torch dependency bloat | slow installs | torch only in the optional Depth Pro extra; core path is ONNX-only |

---

## 8. Milestones

| # | Deliverable | Est. |
|---|---|---|
| M1 | `depth.py` + DA-V2-Small ONNX backend + cache + `/api/depth/*` + depth preview UI | 1 day |
| M2 | Style B flat depth-relief (smallest diff, proves the pipe end-to-end) | 0.5 day |
| M3 | Style A diorama builder + tests + UI controls | 1 day |
| M4 | Style B upright wall-relief + gradient clamp | 0.5 day |
| M5 | Water/sky heuristics + depth-preview band overlay + docs/THIRD_PARTY | 0.5 day |
| M6 (opt) | Depth Pro backend (metric labels, focal-aware perspective comp) | 0.5 day |

Total: **~3.5–4 focused days** to full feature; M1+M2 (~1.5 days) already ships
a working "photo → 3D LEGO terrain" experience.

## 9. Stretch ideas (explicitly out of scope for v1)

- Camera-sweep parallax GIF rendered from the voxel scene (client-side) to show
  off the diorama effect.
- Occlusion inpainting behind panels (nicer off-axis views).
- glTF/Blender export of the *pre-LEGO* displaced mesh for photoreal previews.
- Depth Anything 3 multi-photo mode → true multi-view scenes (bridges to the
  original research doc's COLMAP/InstantMesh stage).
- Interactive "depth brush" to manually fix water/sky regions before building.
