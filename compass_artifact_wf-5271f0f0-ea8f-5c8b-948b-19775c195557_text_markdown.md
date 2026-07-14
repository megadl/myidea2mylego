# Open-Source Multi-View Images → LEGO Model Pipeline: Tools, Comparison, and a Recommended End-to-End Build

## TL;DR
- **No single open-source project does the whole job** (multi-view photos → 3D → voxels → real LEGO bricks → per-layer statistics + BoM + render). The closest single-project "image→LEGO" work, MIT's **Image2Lego**, is a 2021 single-image research prototype with thin/undocumented code and is not production-ready.
- **The right approach is a 3-stage pipeline of mature open-source tools:** (1) **COLMAP/Meshroom** photogrammetry (or **InstantMesh/TripoSR** neural reconstruction) for multi-view → textured mesh; (2) **brickalize** (Python, GPLv3) or **ColouredVoxels2LDR** for mesh → voxel → LEGO bricks with layer-by-layer output; (3) **LDraw ecosystem** (LDView/LeoCAD/LPub3D) for rendering + BoM, with a ~50-line Python LDR parser to compute per-layer brick statistics.
- **Best "buildable + statistics" foundation is `brickalize`**, which already stores the model layer-by-layer and emits 2D per-layer instruction images; pair it with an LDraw exporter for a BrickLink/Rebrickable BoM. For state-of-the-art brick optimization with physical stability, **BrickGPT/LegoGPT** (CMU, MIT license, ICCV 2025 Best Paper) is the most advanced 2025 code but is text-input and grid-limited.

## Key Findings

**1. The pipeline naturally decomposes into four stages, and open-source coverage is strong at every stage except a single unified wrapper.** The stages are: (a) multi-view → 3D mesh; (b) mesh → voxel grid; (c) voxel grid → optimized LEGO bricks (LDraw); (d) LDR → rendering + per-layer statistics + BoM. Every stage has multiple maintained, permissively-licensed options. What does not exist is one repo that ingests a folder of photos and emits a buildable LEGO model with a layered BoM — you assemble it from ~3 components plus glue code.

**2. `brickalize` is the single best-fit "core" for stages (b)+(c)+partial (d).** It is a maintained Python package (PyPI, GPLv3, ~15 GitHub stars, Python 100%) that voxelizes an STL (via trimesh), optionally hollows the shell, places bricks from a user-defined `BrickSet` (1×1, 1×2, 1×3, 1×4, 1×6, 2×2, 2×4, etc.) using a larger-brick-greedy algorithm, generates sparse support pillars for overhangs, **stores the result layer-by-layer in a `BrickModel` object**, renders interactively in Open3D, and **exports 2D per-layer PNG build-instruction images**. Its `BrickModel` "stores placed bricks (size, position, type) per layer" — exactly the data structure needed for per-layer statistics. It does not natively write LDraw or a BoM, but the layered brick list is directly iterable in Python to produce both.

**3. The LEGO/LDraw file format makes per-layer statistics trivial to derive.** An LDraw `.ldr` model line (type 1) is: `1 <colour> x y z a b c d e f g h i <part>.dat`. Every brick is one line encoding colour code, an (x, y, z) position, a 3×3 orientation/scale matrix, and a part filename. Because LDraw's vertical axis is **−Y** (studs point up, i.e., toward negative Y; the bottom of studs sits at y=0 per the parts spec) and standard brick/plate heights are fixed (1 brick = 24 LDU tall, 1 plate = 8 LDU), you can bin lines by their Y coordinate to recover layers, then group by part ID and colour to count quantities. This is a ~50-line Python parser (split each line on whitespace, filter `line[0]=='1'`, read fields 2–5 and 14, bin `y`, `collections.Counter` the `(part, colour)` tuples).

**4. Real-world multi-view input strongly favors classical photogrammetry (COLMAP/Meshroom) over neural single-image models — but neural models are better if you have few, clean views.** COLMAP (BSD, ETH Zurich) and AliceVision Meshroom (MPL2) do full SfM+MVS → dense point cloud → meshed, textured model from many overlapping photos; this is the highest-fidelity route when you have a real object photographed from many angles. If you have only a handful of views or a single clean product shot, **InstantMesh** (Tencent ARC, Apache-2.0) is purpose-built for sparse-view reconstruction (generates 6 novel views then reconstructs a mesh via a transformer LRM with FlexiCubes), and **TripoSR** (Stability AI + Tripo, MIT) is the fastest single-image option (<1 s mesh). All output standard meshes (OBJ/GLB/PLY) that feed directly into voxelization.

**5. The academic "Legolization" line of work is well-documented but the strongest code releases are recent.** The seminal reference is Sheng-Jie Luo, Yonghao Yue, Chun-Kai Huang, Yu-Huan Chung, Sei Imai, Tomoyuki Nishita, and Bing-Yu Chen, "Legolization: Optimizing LEGO Designs," ACM Transactions on Graphics 34(6):222:1–222:12 (Proc. SIGGRAPH Asia 2015) — contributing "a force-based analysis for estimating physical stability... and a layout refinement algorithm that iteratively improves the structure around the weak portion." The original authors did not release production code, but there are course-project reimplementations (`debilin/Legolizer`, `BijoySingh/Legolization-Computer-Graphics`, `dzungpng/brick-optimization-builder` as a Maya plugin). The 2025 state of the art is **BrickGPT/LegoGPT** (CMU), the best-maintained and best-documented open code for *stable* brick layout, though its input is text, not images.

## Details

### Stage A — Multi-view images → 3D mesh

| Tool | Approach | Input | Output | License | Notes |
|---|---|---|---|---|---|
| **COLMAP** | SfM + MVS photogrammetry | Many overlapping photos | Sparse/dense point cloud, Poisson/Delaunay mesh | BSD | Gold standard; GPU recommended for dense MVS. Best for many real photos. |
| **AliceVision Meshroom** | SfM + MVS photogrammetry, node-graph GUI | Many photos | Textured mesh (OBJ) | MPL2 | Most user-friendly full photogrammetry; one-click. |
| **OpenMVG + OpenMVS** | SfM (OpenMVG) + dense/mesh (OpenMVS) | Many photos | Textured mesh | MPL2 / AGPL | Scriptable CLI pipeline; note OpenMVS AGPL copyleft. |
| **nerfstudio (nerfacto)** | NeRF; uses COLMAP poses | Photos/video | Mesh via Poisson export (`ns-export`) | Apache-2.0 | Good for scenes; mesh export usable but noisier than MVS for single objects. |
| **InstantMesh** | Multi-view diffusion + sparse-view LRM | 1 (or few) images | Textured mesh (OBJ/GLB), FlexiCubes topology | Apache-2.0 | Best for few/sparse clean views; ~10 s. State-of-the-art single-image quality. |
| **TripoSR** | Feed-forward LRM | 1 image | Textured mesh | MIT | Fastest (<1 s); single-image, infers occluded geometry. |

**Recommendation for Stage A:** With genuine multi-view captures (many angles of a real object), use **COLMAP** or **Meshroom** for fidelity. If you have only a few views or want speed and are willing to accept "plausible" back-side geometry, use **InstantMesh** (it explicitly targets sparse multi-view). Both produce a mesh you clean/scale before voxelizing.

### Stage B — Mesh → voxel grid

- **trimesh** (`trimesh.voxel.creation.voxelize`, methods `subdivide` / `ray` / `binvox`) — MIT; returns a `VoxelGrid` with a dense boolean occupancy array. This is what `brickalize` uses internally.
- **Open3D** `VoxelGrid.create_from_triangle_mesh(mesh, voxel_size=…)` — MIT; simple and fast, plus point-cloud voxelization with per-voxel average colour (useful to carry colour into brick assignment).
- **binvox** + `trimesh.exchange.binvox` — classic external voxelizer; run-length-encoded `.binvox` files, loadable into trimesh.

Voxel resolution = your LEGO stud resolution. Note the **aspect-ratio caveat**: a LEGO brick is not a cube (plate height 8 LDU vs stud pitch 20 LDU; a brick is 24 LDU tall). If you voxelize with cubic voxels and map 1 voxel → 1 plate layer, the model will look vertically stretched unless you pre-scale the mesh's height (the ColouredVoxels2LDR author recommends scaling height by ~0.8 for brick-height voxels). `brickalize` exposes `aspect_ratio` in `voxelize_stl` to handle this.

### Stage C — Voxel grid → LEGO bricks (legoization) + LDraw

| Project | Input → Output | Layer stats? | LDraw out? | Stability opt? | License / status |
|---|---|---|---|---|---|
| **brickalize** | STL→voxel→BrickModel; STL mesh + per-layer PNGs | **Yes (native layered `BrickModel`)** | No (derive) | Support pillars, greedy merge | GPLv3, maintained, PyPI |
| **ColouredVoxels2LDR** (pennyforge) | MagicaVoxel `.vox`→`.ldr` (coloured) | Per-layer scan; derivable | **Yes** | Merges 1×1s into larger bricks; alternates layer orientation for strength | MIT, 2019, ~27★, stable but old |
| **BinvoxToLDR** (pennyforge) | `.binvox`→optimized `.ldr` | Derivable | **Yes** | Merges + 90° layer rotation | MIT, Python 2.7, archival |
| **3D-to-Lego** (AJaiman) | STL→voxel→(planned LDraw) | Planned layer instructions | Partial/planned | Planned | MIT, early/incomplete |
| **LSculpt** (Bram Lambrecht) | Triangle mesh→`.ldr` (studs-out 1×1 plates) | Surface only (not solid layers) | **Yes** | Orientation optimization for detail, not stability | Open source (C++/Qt), archived on GitHub, in LDraw AIOI |
| **Legolizer / brick-optimization-builder** | Voxel/mesh→brick layout | Partial | Some | Implements Luo 2015 force analysis | Course projects, unmaintained |
| **BrickGPT / LegoGPT** (CMU) | **Text**→bricks; `.txt` + **`.ldr`** + `.png` | Bottom-to-top brick order (layer-derivable) | **Yes (native `.ldr` export)** | **Yes — physics stability + rollback (Gurobi)** | MIT, actively maintained 2025–26, ICCV 2025 Best Paper |
| **brickr** (R) | Coord/table/mosaic→3D rgl model | **Yes (`Level`/z-axis + `build_pieces_table`)** | No | No | MIT, last substantive work ~2020–24 |
| **Bricker** (Blender add-on) | Mesh→brick model; **LDR export** | Via LDR | **Yes** | No | GPLv3 but **paid** ($65, Blender/Superhive Market) |

**Detail on the standout options:**

- **brickalize** (recommended core). The `Brickalizer` static methods run `voxelize_stl()` → `extract_shell_from_3d_array()` (optional hollowing) → `array_to_brick_model(brickset)` → `generate_support()`. The resulting `BrickModel` is "a dictionary of layers, where each layer contains a list of placed bricks (position, size, support status)." `BrickModelVisualizer.save_as_images()` emits per-layer PNGs with stud overlays and ghost-layer previews (build instructions); `save_model()` writes a single STL; `show_model()` gives an interactive Open3D render. It has **no LDraw exporter and no BoM**, but because the layered brick list is a plain Python structure, both are ~30–60 lines of glue.

- **ColouredVoxels2LDR** (recommended LDraw exporter path). Reads a Goxel-exported MagicaVoxel `.vox` (with colour) via py-vox-io and writes a coloured `.ldr`, merging spurious 1×1 columns into larger bricks and alternating brick orientation per layer for structural strength. This is the exact "voxel→LDraw" missing link and is what MIT's Image2Lego adapted for its voxels-to-LEGO step. MIT license, mature (2019), but Python 3.7-era and lightly maintained.

- **BrickGPT / LegoGPT** (CMU; Ava Pun, Kangle Deng, Ruixuan Liu, Deva Ramanan, Changliu Liu, Jun-Yan Zhu; arXiv 2505.05469). This won the **Best Paper Award (Marr Prize) at ICCV 2025** and is the most advanced open brick-optimization code, MIT-licensed and actively maintained (~1.7k stars, ~190 commits, live Gradio demo). It fine-tunes **Llama-3.2-1B-Instruct** (a gated model requiring an HF access token) for next-brick prediction and enforces **physical stability** via a Gurobi static-equilibrium analysis with physics-aware rollback. The stability gain is dramatic: the survey "Prompt-to-Parts" (arXiv:2512.15743) reports the method achieves **"98.8% stability with rollback versus 24% without—a striking demonstration that inference-time constraint enforcement can achieve near-perfect physical validity."** Its CLI emits **three files: `output.png`, `output.txt`, and `output.ldr` (LDraw)** (a sample run reports "Total # bricks: 59"). Bricks are `[h, w, x, y, z]` ordered bottom-to-top, so per-layer statistics fall out directly. **Two big caveats for this use case:** (1) input is **text prompts only** — there is no image conditioning in the model; (2) it is limited to a **20×20×20 grid**, an **8-brick library (1×1, 1×2, 1×4, 1×6, 1×8, 2×2, 2×4, 2×6)**, and **21 trained object categories**. However, the repo ships a **`src/mesh2brick`** module (the "split-and-remerge legolization" used to build its training dataset — **StableText2Lego**, "over 47,000 LEGO structures of over 28,000 unique 3D objects accompanied by detailed captions" — by voxelizing ShapeNet meshes to 20³). That mesh→brick converter *is* reusable for an image-derived mesh and inherits the stability machinery. Gurobi is optional (free academic license; `--use_gurobi False` falls back to a connectivity-based check).

- **brickr** (R). Mature and pleasant for programmatic 3D LEGO from a coordinate/table input, with a native `Level` (z-axis) concept and `build_pieces_table()` / `build_pieces()` for a piece count "sorted by color and size." Its `bricks_from_mosaic()` even lifts a 2D image mosaic into a 3D stack. But it targets rgl rendering, **not** LDraw, and it is not a photogrammetry front-end — you would still need Stages A/B upstream and would be feeding it a voxel coordinate table.

### Stage D — Rendering, BoM, and per-layer statistics from LDraw

Once you have an `.ldr`, the LDraw ecosystem gives you rendering and BoM for free:
- **LDView** (Travis Cobbs) — real-time OpenGL renderer; can export an **HTML parts list**.
- **LeoCAD** and **LPub3D** (trevorsandy) — LPub3D generates building instructions with a graphical **Bill of Materials** and can **export a BrickLink Wanted List XML** and CSV parts list (it uses a `codes.txt` to map LDraw design IDs ↔ BrickLink/LEGO element IDs). LeoCAD/MLCad/BrickStore can likewise export BrickLink XML.
- **BrickStore / BrickStock** — import an LDR/parts list, export **BrickLink XML** for one-click cart/Wanted-List upload with live pricing.
- **BrickLink Wanted List XML** format is `<INVENTORY><ITEM><ITEMTYPE>P</ITEMTYPE><ITEMID>3001</ITEMID><COLOR>…</COLOR><MINQTY>…</MINQTY></ITEM>…</INVENTORY>` — trivial to emit directly from your parsed brick counts, mapping LDraw part IDs and colour codes to BrickLink IDs.
- **Rebrickable** accepts CSV part lists and has an API for availability/pricing; the community `lego_image_converter` (Hugging Face space + GitHub) demonstrates one-click BrickLink-XML/Rebrickable-CSV export with Delta-E CIE2000 colour matching (for mosaics, but the export code is instructive).

**Per-layer statistics glue code (the crux of the user's requirement).** Whether the LDR comes from brickalize (via a small exporter you write), ColouredVoxels2LDR, or BrickGPT, the layered BoM is a short script:
1. Read the `.ldr`; keep lines starting with `1`.
2. Parse fields: `colour = f[1]`, `y = float(f[3])` (LDraw vertical axis), `part = f[14]`.
3. Compute `layer = round((y - y_min) / plate_height)` (8 LDU for plates, 24 for bricks — use your voxelization's actual step).
4. `stats[layer][(part, colour)] += 1` with `collections.defaultdict(Counter)`.
5. Emit per-layer tables and a grand-total BoM; optionally translate `(part, colour)` → BrickLink IDs and write Wanted-List XML.

Because LDraw stores each brick as one flat line with an explicit position and part ID, this parsing is robust and format-stable (the spec is a ratified LDraw.org standard).

### On "single project covers everything"
- **Image2Lego** (MIT; Kyle Lennon, Katharina Fransen, Alexander O'Brien, Yumeng Cao, Matthew Beveridge, Yamin Arefeen, Nikhil Singh, Iddo Drori; arXiv 2108.08477, submitted 19 Aug 2021) is the only published *image→3D→voxel→LEGO→instructions+parts-list* single pipeline — "the first complete approach that allows users to generate real LEGO® sets from 2D images in a single pipeline," using "an octree-structured autoencoder trained on 3D voxelized models" plus a 2D-image encoder to predict a voxel model, then converting voxels→bricks with an algorithm **adapted from ColouredVoxels2LDR**, and generating step-by-step instructions and a brick parts list. **But:** it is **single-image** (the authors explicitly list multi-view reconstruction as future work), the code repo (`krlennon/image2lego`) is minimal (~9 stars, thin documentation), it is a research artifact from 2021, and colour/hollowing are handled with ad-hoc post-processing. It is a proof of concept, not a tool to build on.
- **BlockForge / BlockForge_platform** and various "STL-to-LEGO" GUIs exist but are hobby-grade, JavaScript/early-stage, and not multi-view.

## Recommendations

**Recommended end-to-end pipeline (staged):**

**Stage 1 — Reconstruct a mesh from your multi-view images.**
- Many real photos → **COLMAP** (`github.com/colmap/colmap`, BSD) or **AliceVision Meshroom** (`github.com/alicevision/Meshroom`, MPL2). Export a watertight-ish textured mesh (OBJ/PLY).
- Few/clean views or speed priority → **InstantMesh** (`github.com/TencentARC/InstantMesh`, Apache-2.0); single shot → **TripoSR** (`github.com/VAST-AI-Research/TripoSR`, MIT).
- Clean/repair/scale the mesh in **MeshLab** or **Blender** (make it manifold; set real-world height; correct the LEGO aspect ratio, ≈0.8 vertical pre-scale if using brick-height voxels).

**Stage 2 + 3 — Voxelize and legoize with `brickalize`** (`github.com/CreativeMindstorms/brickalize`, GPLv3, `pip install brickalize`).
- `Brickalizer.voxelize_stl(stl, grid_voxel_count, direction, aspect_ratio=…)` → `extract_shell_from_3d_array` (optional) → `array_to_brick_model(BrickSet([...]))` → `generate_support(...)`.
- You now hold a layered `BrickModel`. Call `save_as_images()` for **per-layer build-instruction PNGs** (visual conversion output) and `show_model()`/`save_model()` for the **3D render/STL**.

**Stage 3b — Emit LDraw + BoM (glue code).**
- Write a ~40-line exporter that walks `BrickModel`'s per-layer brick list and writes LDraw type-1 lines, mapping each brick size → the correct LDraw part `.dat` (e.g., 3005=1×1, 3004=1×2, 3003=2×2, 3001=2×4) and colour → an LDraw colour code. (Alternatively, route voxels through **ColouredVoxels2LDR** via a Goxel `.vox` if you want colour handled and merging done for you.)
- Run the **per-layer statistics parser** (above) on the `.ldr` to produce the layered brick-type/quantity tables and the total BoM; optionally emit **BrickLink Wanted List XML** and/or **Rebrickable CSV**.

**Stage 4 — Render and cross-check the BoM with mature tools.**
- Open the `.ldr` in **LDView** for a high-quality render + HTML parts list, or **LPub3D** for full instructions + graphical BoM + BrickLink-XML export, or **BrickStore** for pricing and cart upload.

**Alternative "stability-first" track (advanced):** If physical stability matters more than colour/multi-view fidelity, take the Stage-1 mesh, voxelize to ≤20³, and feed it through **BrickGPT's `src/mesh2brick`** module (`github.com/AvaLovelace1/BrickGPT`, MIT) to get a stability-checked `.ldr` directly, then run Stages 3b/4. This buys you the force-based stability guarantees from the Luo-2015 lineage but constrains you to its 8-brick library and 20³ grid.

**Staged decision thresholds:**
- If reconstruction quality is poor (holes, noise) → switch COLMAP↔InstantMesh depending on view count; increase photo overlap or run OpenMVS densification.
- If the brick model looks vertically stretched → fix the aspect-ratio pre-scale (Stage 1) or brickalize `aspect_ratio`.
- If you need real buildability/stability → move from brickalize's greedy merge to the BrickGPT mesh2brick/stability track.
- If you need colour → prefer the Open3D coloured voxel grid + ColouredVoxels2LDR path (colour-aware) over brickalize (shape-focused).

## Caveats
- **No turnkey multi-view→LEGO tool exists**; you are integrating ~3 tools + glue. Budget engineering time for mesh cleanup and the LDR exporter/parser.
- **Licensing mix:** COLMAP (BSD), Meshroom/OpenMVG (MPL2), OpenMVS (**AGPL** — copyleft, matters if you redistribute a service), TripoSR/InstantMesh (MIT/Apache-2.0), brickalize/BrickGPT (**GPLv3 / MIT**), ColouredVoxels2LDR (MIT). **Bricker** (Blender) is GPLv3 in source but sold for $65 and not freely distributed — not "open" in practice. BrickLink Studio is **not** open source (and was the subject of a public GPL-violation dispute over Blender-derived code), so avoid depending on it programmatically.
- **BrickGPT/LegoGPT is text-input and grid-limited (20³, 8 bricks, 21 categories)** — do not treat it as an image-to-LEGO solution; only its mesh2brick + stability modules are reusable here, and its brick library list differs across secondary sources (trust the arXiv list: 1×1, 1×2, 1×4, 1×6, 1×8, 2×2, 2×4, 2×6).
- **Image2Lego is a 2021 single-image research prototype** with minimal code; it validates the concept but is not a maintained dependency.
- **LEGO aspect ratio / hollowing / stability** are the three recurring practical pitfalls: cubic voxels distort height; solid voxel fills waste hundreds of internal bricks (hollow the shell); and greedy brick merging does not guarantee the model won't fall apart (only the Luo-2015/BrickGPT stability lineage addresses this).
- **Colour fidelity is limited by the LEGO palette**; use CIE94/CIE2000 colour matching (as brickr and lego_image_converter do), not raw RGB distance, and constrain to a "universal"/available-colour subset.
- **Part-ID mapping** between LDraw, BrickLink, and Rebrickable is imperfect (mold variants, alternate IDs); expect to hand-fix a few unmatched parts when uploading a Wanted List.