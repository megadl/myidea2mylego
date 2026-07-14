"""Unit tests: color science reference data + structural invariants."""

import io
import xml.etree.ElementTree as ET

import numpy as np
import pytest
from PIL import Image

from server import exporters, model3d, mosaic
from server.palette import PALETTE, PaletteMatcher, ciede2000, palette_subset, srgb_to_lab
from server.parts import PART_BY_ID


# ------------------------------------------------------ CIEDE2000 reference
# Published test pairs from Sharma, Wu & Dalal (2005), Table 1.
SHARMA_PAIRS = [
    ((50.0, 2.6772, -79.7751), (50.0, 0.0, -82.7485), 2.0425),
    ((50.0, 3.1571, -77.2803), (50.0, 0.0, -82.7485), 2.8615),
    ((50.0, 2.8361, -74.0200), (50.0, 0.0, -82.7485), 3.4412),
    ((50.0, -1.3802, -84.2814), (50.0, 0.0, -82.7485), 1.0000),
    ((50.0, -1.1848, -84.8006), (50.0, 0.0, -82.7485), 1.0000),
    ((50.0, 0.0, 0.0), (50.0, -1.0, 2.0), 2.3669),
    ((50.0, 2.49, -0.001), (50.0, -2.49, 0.0009), 7.1792),
    ((50.0, -0.001, 2.49), (50.0, 0.0009, -2.49), 4.8045),
    ((50.0, 2.5, 0.0), (50.0, 0.0, -2.5), 4.3065),
    ((50.0, 2.5, 0.0), (73.0, 25.0, -18.0), 27.1492),
    ((50.0, 2.5, 0.0), (61.0, -5.0, 29.0), 22.8977),
    ((50.0, 2.5, 0.0), (56.0, -27.0, -3.0), 31.9030),
    ((50.0, 2.5, 0.0), (58.0, 24.0, 15.0), 19.4535),
    ((50.0, 2.5, 0.0), (50.0, 3.1736, 0.5854), 1.0000),
    ((50.0, 2.5, 0.0), (50.0, 3.2972, 0.0), 1.0000),
    ((60.2574, -34.0099, 36.2677), (60.4626, -34.1751, 39.4387), 1.2644),
    ((63.0109, -31.0961, -5.8663), (62.8187, -29.7946, -4.0864), 1.2630),
    ((35.0831, -44.1164, 3.7933), (35.0232, -40.0716, 1.5901), 1.8645),
    ((22.7233, 20.0904, -46.6940), (23.0331, 14.9730, -42.5619), 2.0373),
    ((2.0776, 0.0795, -1.1350), (0.9033, -0.0636, -0.5514), 0.9082),
]


@pytest.mark.parametrize("lab1,lab2,expected", SHARMA_PAIRS)
def test_ciede2000_reference_pairs(lab1, lab2, expected):
    got = float(ciede2000(np.array([lab1]), np.array([lab2]))[0, 0])
    assert got == pytest.approx(expected, abs=1e-4)


def test_ciede2000_symmetry_and_identity():
    a = np.array([[50.0, 10.0, -30.0]])
    b = np.array([[55.0, -12.0, 8.0]])
    assert float(ciede2000(a, a)[0, 0]) == pytest.approx(0.0, abs=1e-12)
    assert float(ciede2000(a, b)[0, 0]) == pytest.approx(float(ciede2000(b, a)[0, 0]), abs=1e-9)


def test_srgb_to_lab_white_black():
    lab = srgb_to_lab(np.array([[255.0, 255.0, 255.0], [0.0, 0.0, 0.0]]))
    assert lab[0, 0] == pytest.approx(100.0, abs=0.01)
    assert abs(lab[0, 1]) < 0.01 and abs(lab[0, 2]) < 0.01
    assert lab[1, 0] == pytest.approx(0.0, abs=0.01)


# ------------------------------------------------------------------ palette

def test_palette_ids_unique_and_sane():
    ldraw = [c.ldraw for c in PALETTE]
    bl = [c.bricklink for c in PALETTE]
    names = [c.name for c in PALETTE]
    assert len(set(ldraw)) == len(ldraw)
    assert len(set(bl)) == len(bl)
    assert len(set(names)) == len(names)
    for c in PALETTE:
        assert all(0 <= v <= 255 for v in c.rgb)


def test_matcher_picks_exact_palette_colors():
    m = PaletteMatcher(PALETTE)
    for c in PALETTE:
        assert m.match_one(c.rgb) == c.index, f"{c.name} did not match itself"


def test_near_black_matches_black():
    """(1,1,1) on the 0-255 scale is near-black, not white (scale-guess bug)."""
    m = PaletteMatcher(PALETTE)
    assert PALETTE[m.match_one((1, 1, 1))].name == "Black"


def test_rebrickable_color_ids():
    by_name = {c.name: c for c in PALETTE}
    # Three colors diverge from LDraw codes (verified vs Rebrickable colors.csv)
    assert by_name["Yellowish Green"].rebrickable == 158
    assert by_name["Olive Green"].rebrickable == 326
    assert by_name["Coral"].rebrickable == 1050
    # Everything else follows the LDraw code.
    for c in PALETTE:
        if c.name not in ("Yellowish Green", "Olive Green", "Coral"):
            assert c.rebrickable == c.ldraw


def test_palette_subsets():
    assert len(palette_subset("grayscale")) == 4
    assert len(palette_subset("classic")) == 10
    assert len(palette_subset("full")) == len(PALETTE)


# ------------------------------------------------------------------- mosaic

def _checker_image(px=64):
    img = Image.new("RGB", (px, px), (255, 255, 255))
    for y in range(px):
        for x in range(px):
            if (x // 8 + y // 8) % 2:
                img.putpixel((x, y), (200, 30, 20))
    return img


def test_mosaic_grid_shape_and_merge_conservation():
    m = PaletteMatcher(PALETTE)
    grid = mosaic.image_to_grid(_checker_image(), 32, m)
    assert grid.shape == (32, 32)

    for optimize in (True, False):
        placements = mosaic.merge_plates(grid, optimize=optimize)
        # Total studs covered must equal the grid.
        assert sum(p["length"] for p in placements) == grid.size
        # No overlaps, full cover.
        covered = np.zeros(grid.shape, dtype=int)
        for p in placements:
            covered[p["row"], p["col"] : p["col"] + p["length"]] += 1
            part = PART_BY_ID[p["part"]]
            assert part.length == p["length"] and part.width == 1
            # Placement color matches every stud underneath.
            assert (grid[p["row"], p["col"] : p["col"] + p["length"]] == p["color"]).all()
        assert (covered == 1).all()


def test_split_run_uses_largest_plates():
    assert mosaic._split_run(8, [8, 6, 4, 3, 2, 1]) == [8]
    assert mosaic._split_run(7, [8, 6, 4, 3, 2, 1]) == [6, 1]
    assert mosaic._split_run(5, [8, 6, 4, 3, 2, 1]) == [4, 1]
    assert sum(mosaic._split_run(23, [8, 6, 4, 3, 2, 1])) == 23


# ----------------------------------------------------------------- 3D model

def _simple_grid():
    """Solid 6×4×3 box in one color (palette index 2)."""
    return np.full((3, 4, 6), 2, dtype=np.int32)


def test_place_bricks_exact_cover():
    grid = _simple_grid()
    bricks = model3d.place_bricks(grid)
    covered = np.zeros_like(grid)
    for b in bricks:
        assert grid[b.layer, b.z : b.z + b.zlen, b.x : b.x + b.xlen].min() == b.color
        covered[b.layer, b.z : b.z + b.zlen, b.x : b.x + b.xlen] += 1
        part = PART_BY_ID[b.part]
        assert {part.width, part.length} == {min(b.xlen, b.zlen), max(b.xlen, b.zlen)}
    assert (covered == 1).all()


def test_place_bricks_prefers_large_parts():
    bricks = model3d.place_bricks(_simple_grid())
    # A 6×4 solid layer tiles into three 2×4 bricks; three layers → 9 bricks.
    assert len(bricks) == 9
    assert all(b.part == "3001" for b in bricks)


def test_alternating_orientation():
    bricks = model3d.place_bricks(np.full((2, 8, 8), 0, dtype=np.int32))
    even = [b for b in bricks if b.layer == 0]
    odd = [b for b in bricks if b.layer == 1]
    assert any(b.xlen > b.zlen for b in even)   # long axis along x
    assert any(b.zlen > b.xlen for b in odd)    # long axis along z


def test_stability_report():
    grid = np.full((2, 2, 2), model3d.EMPTY, dtype=np.int32)
    grid[0, 0, 0] = 1
    grid[1, 0, 0] = 1  # directly on top → stable
    bricks = model3d.place_bricks(grid)
    assert model3d.stability_report(bricks)["buildable"]

    grid2 = np.full((2, 2, 4), model3d.EMPTY, dtype=np.int32)
    grid2[0, 0, 0] = 1
    grid2[1, 1, 3] = 1  # floating corner brick
    rep = model3d.stability_report(model3d.place_bricks(grid2))
    assert rep["floating_bricks"] == 1


def test_hollow_keeps_shell():
    grid = np.zeros((6, 6, 6), dtype=np.int32)
    hollowed = model3d.hollow(grid)
    assert (hollowed[0] != model3d.EMPTY).all()          # bottom face kept
    assert hollowed[3, 3, 3] == model3d.EMPTY            # core removed
    assert (hollowed[:, 0, :] != model3d.EMPTY).all()    # walls kept


def test_relief_always_buildable():
    rng = np.random.default_rng(7)
    img = Image.fromarray(rng.integers(0, 255, (40, 40, 3), dtype=np.uint8))
    m = PaletteMatcher(PALETTE)
    grid = model3d.voxelize_relief(img, 24, 8, m)
    bricks = model3d.place_bricks(grid)
    assert model3d.stability_report(bricks)["buildable"]


def test_statue_from_clean_silhouette():
    img = Image.new("RGB", (80, 80), (255, 255, 255))
    for y in range(20, 70):
        for x in range(25, 55):
            img.putpixel((x, y), (30, 60, 200))
    m = PaletteMatcher(PALETTE)
    grid = model3d.voxelize_statue(img, 24, 4, m)
    bricks = model3d.place_bricks(grid)
    assert bricks, "statue produced no bricks"
    assert model3d.stability_report(bricks)["buildable"]


# ---------------------------------------------------------------- exporters

def _sample_bricks():
    return model3d.place_bricks(_simple_grid())


def test_ldraw_output_valid():
    bricks = _sample_bricks()
    ldr = exporters.bricks_to_ldraw(bricks, PALETTE, "test")
    type1 = [l for l in ldr.splitlines() if l.startswith("1 ")]
    assert len(type1) == len(bricks)
    for line in type1:
        f = line.split()
        assert len(f) == 15
        assert f[14].endswith(".dat")
        float_fields = f[2:14]
        [float(v) for v in float_fields]  # parses
    # one STEP per layer
    assert ldr.count("0 STEP") == 3


def test_ldraw_layer_binning_roundtrip():
    """The research doc's per-layer parser: bin type-1 lines by Y."""
    bricks = _sample_bricks()
    ldr = exporters.bricks_to_ldraw(bricks, PALETTE, "test")
    ys = sorted({float(l.split()[3]) for l in ldr.splitlines() if l.startswith("1 ")})
    assert len(ys) == 3           # three distinct layers
    assert ys[1] - ys[0] == 24.0  # brick height in LDU


def test_ldraw_z_negated_no_mirror():
    """Grid depth must map to -z in LDraw or stud-side views mirror the image."""
    bricks = _sample_bricks()
    ldr = exporters.bricks_to_ldraw(bricks, PALETTE, "test")
    zs = [float(l.split()[4]) for l in ldr.splitlines() if l.startswith("1 ")]
    assert all(z <= 0 for z in zs)

    grid = np.array([[0, 1], [2, 3]], dtype=np.int32)
    placements = mosaic.merge_plates(grid, optimize=False)
    mldr = exporters.mosaic_to_ldraw(placements, PALETTE, "test")
    mzs = [float(l.split()[4]) for l in mldr.splitlines() if l.startswith("1 ")]
    assert all(z < 0 for z in mzs)


def test_bom_totals_consistent():
    bricks = _sample_bricks()
    bom = exporters.build_bom([(b.part, b.color) for b in bricks], PALETTE)
    totals = exporters.bom_totals(bom)
    assert totals["pieces"] == len(bricks)
    stud_area = sum(PART_BY_ID[r["part"]].area * r["qty"] for r in bom)
    assert stud_area == 6 * 4 * 3  # every voxel covered exactly once


def test_bricklink_xml_well_formed():
    bom = exporters.build_bom([("3001", 0), ("3024", 3)], PALETTE)
    root = ET.fromstring(exporters.bricklink_xml(bom))
    assert root.tag == "INVENTORY"
    items = list(root)
    assert len(items) == 2
    for item in items:
        assert item.find("ITEMTYPE").text == "P"
        assert int(item.find("MINQTY").text) > 0
        assert int(item.find("COLOR").text) > 0


def test_rebrickable_csv_and_bom_csv():
    bom = exporters.build_bom([("3005", 1)], PALETTE)
    csv_text = exporters.rebrickable_csv(bom)
    lines = csv_text.strip().splitlines()
    assert lines[0] == "Part,Color,Quantity"
    assert lines[1].startswith("3005,")
    assert "Qty" in exporters.bom_csv(bom).splitlines()[0]


def test_layer_stats_match_bricks():
    bricks = _sample_bricks()
    stats = exporters.layer_stats(bricks, PALETTE)
    assert sum(s["pieces"] for s in stats) == len(bricks)
    assert [s["layer"] for s in stats] == [0, 1, 2]


# ---------------------------------------------------------------- api level

def test_full_api_roundtrip(tmp_path):
    from fastapi.testclient import TestClient
    from server.main import app

    client = TestClient(app)
    buf = io.BytesIO()
    _checker_image().save(buf, format="PNG")

    for mode in ("mosaic", "statue", "relief"):
        buf.seek(0)
        res = client.post(
            "/api/convert",
            files={"file": ("test.png", buf.getvalue(), "image/png")},
            data={"mode": mode, "width": "24"},
        )
        assert res.status_code == 200, res.text
        data = res.json()
        assert data["totals"]["pieces"] > 0
        assert data["files"]["zip"]
        z = client.get(data["files"]["zip"])
        assert z.status_code == 200
