"""LEGO color palette and perceptual color matching (CIEDE2000).

Each palette entry maps one physical LEGO color across the three ID systems
the export files need:
  - ldraw:     LDraw color code (used in .ldr files; Rebrickable uses the same
               codes for almost all solid colors)
  - bricklink: BrickLink color ID (used in Wanted List XML)
  - lego:      official LEGO material/color ID (used on Pick a Brick)

RGB values are the LDraw/Rebrickable reference values for each color.
Matching uses CIEDE2000 in Lab space — raw RGB distance picks visibly wrong
bricks, especially in skin tones and grays.
"""

from __future__ import annotations

import numpy as np

# name, hex, ldraw, bricklink, lego
_COLOR_ROWS = [
    ("White",              "F4F4F4", 15,  1,   1),
    ("Black",              "1B2A34", 0,   11,  26),
    ("Red",                "B40000", 4,   5,   21),
    ("Dark Red",           "720012", 320, 59,  154),
    ("Blue",               "1E5AA8", 1,   7,   23),
    ("Dark Blue",          "19325A", 272, 63,  140),
    ("Medium Blue",        "7396C8", 73,  42,  102),
    ("Bright Light Blue",  "9DC3F7", 212, 105, 212),
    ("Dark Azure",         "469BC3", 321, 153, 321),
    ("Medium Azure",       "68C3E2", 322, 156, 322),
    ("Sand Blue",          "70819A", 379, 55,  135),
    ("Yellow",             "FAC80A", 14,  3,   24),
    ("Bright Light Yellow","FFEC6C", 226, 103, 226),
    ("Bright Light Orange","F9BA61", 191, 110, 191),
    ("Orange",             "D67923", 25,  4,   106),
    ("Dark Orange",        "91501C", 484, 68,  38),
    ("Green",              "00852B", 2,   6,   28),
    ("Dark Green",         "00451A", 288, 80,  141),
    ("Bright Green",       "58AB41", 10,  36,  37),
    ("Lime",               "9ACA3C", 27,  34,  119),
    ("Yellowish Green",    "C2E4A7", 326, 158, 326),
    ("Olive Green",        "77774E", 330, 155, 330),
    ("Sand Green",         "708E7C", 378, 48,  151),
    ("Dark Turquoise",     "069D9F", 3,   39,  107),
    ("Tan",                "DDC48E", 19,  2,   5),
    ("Dark Tan",           "897D62", 28,  69,  138),
    ("Nougat",             "D09168", 92,  28,  18),
    ("Light Nougat",       "F6D7B3", 78,  90,  283),
    ("Medium Nougat",      "AA7D55", 84,  150, 312),
    ("Reddish Brown",      "5F3109", 70,  88,  192),
    ("Dark Brown",         "352100", 308, 120, 308),
    ("Light Bluish Gray",  "A0A5A9", 71,  86,  194),
    ("Dark Bluish Gray",   "6C6E68", 72,  85,  199),
    ("Magenta",            "901F76", 26,  71,  124),
    ("Dark Pink",          "C870A0", 5,   47,  221),
    ("Bright Pink",        "E4ADC8", 29,  104, 222),
    ("Coral",              "FF698F", 353, 220, 353),
    ("Dark Purple",        "3F3691", 85,  89,  268),
    ("Medium Lavender",    "AC78BA", 30,  157, 324),
    ("Lavender",           "E1D5ED", 31,  154, 325),
]


# Rebrickable color IDs equal the LDraw code for every palette color EXCEPT
# these three (verified against Rebrickable's official colors.csv):
_REBRICKABLE_OVERRIDES = {"Yellowish Green": 158, "Olive Green": 326, "Coral": 1050}


class LegoColor:
    __slots__ = ("index", "name", "rgb", "hex", "ldraw", "bricklink", "lego", "rebrickable")

    def __init__(self, index, name, hex_, ldraw, bricklink, lego):
        self.index = index
        self.name = name
        self.hex = "#" + hex_
        self.rgb = tuple(int(hex_[i : i + 2], 16) for i in (0, 2, 4))
        self.ldraw = ldraw
        self.bricklink = bricklink
        self.lego = lego
        self.rebrickable = _REBRICKABLE_OVERRIDES.get(name, ldraw)

    def as_dict(self):
        return {
            "index": self.index,
            "name": self.name,
            "hex": self.hex,
            "ldraw": self.ldraw,
            "bricklink": self.bricklink,
            "lego": self.lego,
            "rebrickable": self.rebrickable,
        }


PALETTE: list[LegoColor] = [
    LegoColor(i, *row) for i, row in enumerate(_COLOR_ROWS)
]

GRAYSCALE_NAMES = {"White", "Black", "Light Bluish Gray", "Dark Bluish Gray"}


def palette_subset(mode: str) -> list[LegoColor]:
    """'full' | 'grayscale' | 'classic' (the 10 most common colors)."""
    if mode == "grayscale":
        return [c for c in PALETTE if c.name in GRAYSCALE_NAMES]
    if mode == "classic":
        keep = {
            "White", "Black", "Red", "Blue", "Yellow", "Green",
            "Tan", "Orange", "Light Bluish Gray", "Dark Bluish Gray",
        }
        return [c for c in PALETTE if c.name in keep]
    return list(PALETTE)


# ---------------------------------------------------------------- color math

def srgb_to_lab(rgb: np.ndarray) -> np.ndarray:
    """sRGB in 0–255 (…,3) -> CIELAB (…,3), D65 reference white.

    Input is ALWAYS interpreted on the 0–255 scale — guessing the scale from
    the values misreads near-black pixels like (1,1,1) as full brightness.
    """
    c = np.asarray(rgb, dtype=np.float64) / 255.0
    c = np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    m = np.array(
        [
            [0.4124564, 0.3575761, 0.1804375],
            [0.2126729, 0.7151522, 0.0721750],
            [0.0193339, 0.1191920, 0.9503041],
        ]
    )
    xyz = c @ m.T
    xyz /= np.array([0.95047, 1.0, 1.08883])
    eps, kappa = (6 / 29) ** 3, (29 / 6) ** 2 / 3
    f = np.where(xyz > eps, np.cbrt(xyz), kappa * xyz + 4 / 29)
    lab = np.empty_like(xyz)
    lab[..., 0] = 116 * f[..., 1] - 16
    lab[..., 1] = 500 * (f[..., 0] - f[..., 1])
    lab[..., 2] = 200 * (f[..., 1] - f[..., 2])
    return lab


def ciede2000(lab1: np.ndarray, lab2: np.ndarray) -> np.ndarray:
    """CIEDE2000 distance matrix. lab1 (N,3), lab2 (M,3) -> (N,M).

    Implementation follows Sharma, Wu & Dalal (2005), including the hue
    wrap-around rules; verified against the paper's published test pairs.
    """
    lab1 = np.atleast_2d(lab1)[:, None, :]
    lab2 = np.atleast_2d(lab2)[None, :, :]
    L1, a1, b1 = lab1[..., 0], lab1[..., 1], lab1[..., 2]
    L2, a2, b2 = lab2[..., 0], lab2[..., 1], lab2[..., 2]

    C1 = np.hypot(a1, b1)
    C2 = np.hypot(a2, b2)
    Cbar = (C1 + C2) / 2
    G = 0.5 * (1 - np.sqrt(Cbar**7 / (Cbar**7 + 25.0**7)))
    a1p, a2p = (1 + G) * a1, (1 + G) * a2
    C1p = np.hypot(a1p, b1)
    C2p = np.hypot(a2p, b2)

    h1p = np.degrees(np.arctan2(b1, a1p)) % 360
    h2p = np.degrees(np.arctan2(b2, a2p)) % 360
    h1p = np.where((np.abs(a1p) < 1e-12) & (np.abs(b1) < 1e-12), 0.0, h1p)
    h2p = np.where((np.abs(a2p) < 1e-12) & (np.abs(b2) < 1e-12), 0.0, h2p)

    dLp = L2 - L1
    dCp = C2p - C1p

    zero_chroma = (C1p * C2p) == 0
    dhp = h2p - h1p
    dhp = np.where(dhp > 180, dhp - 360, dhp)
    dhp = np.where(dhp < -180, dhp + 360, dhp)
    dhp = np.where(zero_chroma, 0.0, dhp)
    dHp = 2 * np.sqrt(C1p * C2p) * np.sin(np.radians(dhp) / 2)

    Lbp = (L1 + L2) / 2
    Cbp = (C1p + C2p) / 2
    hsum = h1p + h2p
    hdiff = np.abs(h1p - h2p)
    hbp = np.where(
        hdiff <= 180,
        hsum / 2,
        np.where(hsum < 360, (hsum + 360) / 2, (hsum - 360) / 2),
    )
    hbp = np.where(zero_chroma, hsum, hbp)

    T = (
        1
        - 0.17 * np.cos(np.radians(hbp - 30))
        + 0.24 * np.cos(np.radians(2 * hbp))
        + 0.32 * np.cos(np.radians(3 * hbp + 6))
        - 0.20 * np.cos(np.radians(4 * hbp - 63))
    )
    dtheta = 30 * np.exp(-(((hbp - 275) / 25) ** 2))
    RC = 2 * np.sqrt(Cbp**7 / (Cbp**7 + 25.0**7))
    SL = 1 + 0.015 * (Lbp - 50) ** 2 / np.sqrt(20 + (Lbp - 50) ** 2)
    SC = 1 + 0.045 * Cbp
    SH = 1 + 0.015 * Cbp * T
    RT = -np.sin(np.radians(2 * dtheta)) * RC

    return np.sqrt(
        (dLp / SL) ** 2
        + (dCp / SC) ** 2
        + (dHp / SH) ** 2
        + RT * (dCp / SC) * (dHp / SH)
    )


class PaletteMatcher:
    """Matches RGB pixels to the nearest LEGO color by CIEDE2000."""

    def __init__(self, colors: list[LegoColor]):
        self.colors = colors
        self._rgb = np.array([c.rgb for c in colors], dtype=np.float64)
        self._lab = srgb_to_lab(self._rgb)

    def match(self, rgb_pixels: np.ndarray) -> np.ndarray:
        """rgb_pixels (N,3) -> palette indices (N,) into self.colors."""
        pix = np.asarray(rgb_pixels, dtype=np.float64).reshape(-1, 3)
        lab = srgb_to_lab(pix)
        # Chunk to bound peak memory on large inputs.
        out = np.empty(len(lab), dtype=np.int32)
        step = 4096
        for i in range(0, len(lab), step):
            d = ciede2000(lab[i : i + step], self._lab)
            out[i : i + step] = np.argmin(d, axis=1)
        return out

    def match_one(self, rgb: tuple) -> int:
        return int(self.match(np.array([rgb]))[0])
