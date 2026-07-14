"""Exports: LDraw model, BrickLink Wanted List XML, Rebrickable CSV, BoM.

LDraw geometry facts used here (LDraw.org spec):
- 1 stud pitch = 20 LDU, brick height = 24 LDU, plate height = 8 LDU.
- -Y is up, so higher layers get more negative y.
- A type-1 line is: 1 <color> x y z  a b c d e f g h i  <part>.dat
- Standard rectangular parts are modeled with the origin at the center of
  the part's top face (studs point up beyond it) and the long axis along x.
"""

from __future__ import annotations

import csv
import io
from collections import Counter, defaultdict
from xml.sax.saxutils import escape

from .model3d import PlacedBrick
from .palette import LegoColor
from .parts import PART_BY_ID

STUD_LDU = 20
BRICK_LDU = 24
PLATE_LDU = 8

_IDENTITY = "1 0 0 0 1 0 0 0 1"
_ROT_Y90 = "0 0 1 0 1 0 -1 0 0"


# ------------------------------------------------------------------ LDraw

def bricks_to_ldraw(bricks: list[PlacedBrick], palette: list[LegoColor], title: str) -> str:
    lines = [
        f"0 {title}",
        "0 Name: model.ldr",
        "0 Author: MyIDEA2MyLEGO",
        "0 !LDRAW_ORG Unofficial_Model",
        "0 BFC CERTIFY CCW",
    ]
    last_layer = None
    for b in sorted(bricks, key=lambda b: (b.layer, b.z, b.x)):
        if b.layer != last_layer:
            if last_layer is not None:
                lines.append("0 STEP")
            lines.append(f"0 // Layer {b.layer + 1}")
            last_layer = b.layer
        cx = (b.x + b.xlen / 2) * STUD_LDU
        # z is negated: LDraw is right-handed with -Y up, so grid depth must
        # map to -z or every stud-side view is a mirror image of the input.
        cz = -(b.z + b.zlen / 2) * STUD_LDU
        y = -BRICK_LDU * b.layer
        matrix = _ROT_Y90 if b.rotated else _IDENTITY
        color = palette[b.color].ldraw
        lines.append(f"1 {color} {_n(cx)} {_n(y)} {_n(cz)} {matrix} {b.part}.dat")
    lines.append("0 STEP")
    return "\n".join(lines) + "\n"


def mosaic_to_ldraw(placements: list[dict], palette: list[LegoColor], title: str) -> str:
    """Mosaic laid flat: rows run along z, plates along x, one plate high."""
    lines = [
        f"0 {title}",
        "0 Name: mosaic.ldr",
        "0 Author: MyIDEA2MyLEGO",
        "0 !LDRAW_ORG Unofficial_Model",
    ]
    last_row = None
    for p in sorted(placements, key=lambda p: (p["row"], p["col"])):
        if p["row"] != last_row:
            if last_row is not None:
                lines.append("0 STEP")
            lines.append(f"0 // Row {p['row'] + 1}")
            last_row = p["row"]
        cx = (p["col"] + p["length"] / 2) * STUD_LDU
        cz = -(p["row"] + 0.5) * STUD_LDU  # negated: see bricks_to_ldraw
        color = palette[p["color"]].ldraw
        lines.append(f"1 {color} {_n(cx)} 0 {_n(cz)} {_IDENTITY} {p['part']}.dat")
    lines.append("0 STEP")
    return "\n".join(lines) + "\n"


def _n(v: float) -> str:
    return f"{v:.6g}"  # 30.0 -> "30", 30.5 stays "30.5"


# ------------------------------------------------------------ BoM & files

def build_bom(items: list[tuple[str, int]], palette: list[LegoColor]) -> list[dict]:
    """items: (part_design_id, palette_color_index) per placed piece."""
    counts = Counter(items)
    bom = []
    for (part_id, color_idx), qty in counts.items():
        part = PART_BY_ID[part_id]
        color = palette[color_idx]
        bom.append(
            {
                "part": part_id,
                "part_name": part.name,
                "color": color.as_dict(),
                "qty": qty,
                "est_price_usd": round(part.price_usd * qty, 2),
                "est_weight_g": round(part.weight_g * qty, 1),
                "bricklink_url": (
                    f"https://www.bricklink.com/v2/catalog/catalogitem.page"
                    f"?P={part_id}&C={color.bricklink}#T=S&C={color.bricklink}"
                ),
                "pick_a_brick_query": f"{part_id}",
            }
        )
    bom.sort(key=lambda r: (-r["qty"], r["part"], r["color"]["name"]))
    return bom


def bom_totals(bom: list[dict]) -> dict:
    return {
        "pieces": sum(r["qty"] for r in bom),
        "lots": len(bom),
        "est_price_usd": round(sum(r["est_price_usd"] for r in bom), 2),
        "est_weight_g": round(sum(r["est_weight_g"] for r in bom), 1),
    }


def bricklink_xml(bom: list[dict]) -> str:
    """BrickLink Wanted List upload format."""
    rows = []
    for r in bom:
        rows.append(
            "  <ITEM>"
            "<ITEMTYPE>P</ITEMTYPE>"
            f"<ITEMID>{escape(r['part'])}</ITEMID>"
            f"<COLOR>{r['color']['bricklink']}</COLOR>"
            f"<MINQTY>{r['qty']}</MINQTY>"
            "<CONDITION>N</CONDITION>"
            "</ITEM>"
        )
    return "<INVENTORY>\n" + "\n".join(rows) + "\n</INVENTORY>\n"


def rebrickable_csv(bom: list[dict]) -> str:
    """Rebrickable part-list CSV (uses Rebrickable's own color IDs)."""
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Part", "Color", "Quantity"])
    for r in bom:
        w.writerow([r["part"], r["color"]["rebrickable"], r["qty"]])
    return buf.getvalue()


def bom_csv(bom: list[dict]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(
        ["Part", "Part name", "Color", "BrickLink color ID", "LDraw color",
         "LEGO color ID", "Qty", "Est. price USD", "Est. weight g"]
    )
    for r in bom:
        c = r["color"]
        w.writerow(
            [r["part"], r["part_name"], c["name"], c["bricklink"], c["ldraw"],
             c["lego"], r["qty"], r["est_price_usd"], r["est_weight_g"]]
        )
    return buf.getvalue()


def layer_stats(bricks: list[PlacedBrick], palette: list[LegoColor]) -> list[dict]:
    """Per-layer piece counts — the research doc's 'layered BoM'."""
    layers: dict[int, Counter] = defaultdict(Counter)
    for b in bricks:
        layers[b.layer][(b.part, b.color)] += 1
    out = []
    for layer in sorted(layers):
        rows = [
            {
                "part": part,
                "part_name": PART_BY_ID[part].name,
                "color": palette[color].as_dict(),
                "qty": qty,
            }
            for (part, color), qty in sorted(
                layers[layer].items(), key=lambda kv: -kv[1]
            )
        ]
        out.append(
            {"layer": layer, "pieces": sum(r["qty"] for r in rows), "parts": rows}
        )
    return out
