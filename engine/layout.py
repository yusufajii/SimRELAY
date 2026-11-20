"""
Single-line diagram coordinates (display only).

Kept apart from the electrical data so that layout changes do not invalidate the
simulation cache (this file is excluded from the engine fingerprint).
Compact layout: trunk at y = 300, lateral steps of 95, viewBox about 1817 x 568 so the
diagram fills a wide, short panel at a readable scale.
"""
M = 300          # main trunk
S = 95           # lateral step

COORDS = {
    "800": (130, M),
    "802": (230, M),
    "806": (306, M),
    "808": (382, M),
    "810": (382, M + S),
    "812": (458, M),
    "814": (534, M),
    "850": (646, M),
    "816": (722, M),
    "818": (722, M - S),
    "820": (722, M - 2 * S),
    "822": (798, M - 2 * S),
    "824": (798, M),
    "826": (798, M + S),
    "828": (874, M),
    "830": (1004, M),
    "854": (1080, M),
    "856": (1080, M + S),
    "852": (1156, M),
    "832": (1268, M),
    "888": (1268, M + S),
    "890": (1268, M + 2 * S),
    "858": (1344, M),
    "864": (1344, M - S),
    "834": (1509, M),
    "842": (1509, M - S),
    "844": (1509, M - 2 * S),
    "846": (1585, M - 2 * S),
    "848": (1661, M - 2 * S),
    "860": (1585, M),
    "836": (1661, M),
    "840": (1737, M),
    "862": (1661, M + S),
    "838": (1661, M + 2 * S),
    "B01": (290, M + 215),
    "B02": (390, M + 215),
    "B03": (490, M + 215),
    "B04": (590, M + 215),
    "B05": (490, M + 125),
}
