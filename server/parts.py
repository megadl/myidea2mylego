"""LEGO part catalog used by the converters.

Design IDs are the classic molds that BrickLink, Rebrickable, LDraw and
LEGO Pick a Brick all agree on. Prices are rough BrickLink "avg new" USD
estimates for common colors — good enough for a budget estimate, clearly
labeled as such in the UI. Weights are approximate grams per part.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Part:
    design_id: str   # e.g. "3001"
    name: str        # e.g. "Brick 2 x 4"
    width: int       # studs across (short side)
    length: int      # studs along (long side)
    kind: str        # "brick" | "plate"
    price_usd: float
    weight_g: float

    @property
    def area(self) -> int:
        return self.width * self.length


# Plates (height 8 LDU, 3.2 mm) — used by mosaics.
PLATES = [
    Part("3460", "Plate 1 x 8", 1, 8, "plate", 0.12, 1.28),
    Part("3666", "Plate 1 x 6", 1, 6, "plate", 0.09, 0.96),
    Part("3710", "Plate 1 x 4", 1, 4, "plate", 0.06, 0.64),
    Part("3623", "Plate 1 x 3", 1, 3, "plate", 0.05, 0.49),
    Part("3023", "Plate 1 x 2", 1, 2, "plate", 0.04, 0.33),
    Part("3024", "Plate 1 x 1", 1, 1, "plate", 0.03, 0.16),
]

# Bricks (height 24 LDU, 9.6 mm) — used by 3D models.
BRICKS = [
    Part("3001", "Brick 2 x 4", 2, 4, "brick", 0.16, 2.32),
    Part("3002", "Brick 2 x 3", 2, 3, "brick", 0.14, 1.75),
    Part("3003", "Brick 2 x 2", 2, 2, "brick", 0.10, 1.16),
    Part("3008", "Brick 1 x 8", 1, 8, "brick", 0.22, 3.15),
    Part("3009", "Brick 1 x 6", 1, 6, "brick", 0.15, 2.35),
    Part("3010", "Brick 1 x 4", 1, 4, "brick", 0.10, 1.60),
    Part("3622", "Brick 1 x 3", 1, 3, "brick", 0.09, 1.20),
    Part("3004", "Brick 1 x 2", 1, 2, "brick", 0.06, 0.80),
    Part("3005", "Brick 1 x 1", 1, 1, "brick", 0.05, 0.45),
]

PART_BY_ID = {p.design_id: p for p in PLATES + BRICKS}

# Placement order: biggest area first so greedy merging prefers fewer,
# larger, cheaper-per-stud parts.
PLATES_BY_AREA = sorted(PLATES, key=lambda p: -p.area)
BRICKS_BY_AREA = sorted(BRICKS, key=lambda p: -p.area)

PLATE_1X1 = PART_BY_ID["3024"]

# Stud pitch is 8 mm; a brick is 9.6 mm tall, a plate 3.2 mm.
STUD_MM = 8.0
BRICK_MM = 9.6
PLATE_MM = 3.2
