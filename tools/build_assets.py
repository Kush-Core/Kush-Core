#!/usr/bin/env python3
"""Reproducible generator for the profile's static SVG assets.

Colours come from tokens.json and glyph outlines from fonts/. Every piece of
text is converted to <path> outlines, so the SVGs load no fonts and reference
no external resource.

Outputs (both themes):
    assets/frontispiece-{dark,light}.svg   1200x300
    assets/armory-{dark,light}.svg         1200x260
    assets/seal-{linkedin,email}-{dark,light}.svg   48x48

Usage:
    python tools/build_assets.py              # build assets
    python tools/build_assets.py --check      # build, then validate every SVG
    python tools/build_assets.py --preview    # also write preview/index.html
"""

from __future__ import annotations

import argparse
import base64
import cmath
import html
import json
import math
import re
import struct
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
TOKENS = json.loads((ROOT / "tokens.json").read_text(encoding="utf-8"))
SVG_NS = "http://www.w3.org/2000/svg"
MAX_BYTES = 150_000
REDUCED_MOTION = TOKENS["motion"]["reduced_motion_css"]
THEMES = ("dark", "light")

NAME_TEXT = "Kushagra Singh"
SUBTITLE_TEXT = "Backend & AI Engineer · Python · FastAPI · Neo4j · LLM pipelines"
ARMORY = [
    ("Languages", ["Python", "TypeScript", "C++", "SQL"]),
    ("Backend", ["FastAPI", "Pydantic", "Uvicorn", "PyJWT", "Argon2"]),
    ("Graph & Data", ["Neo4j", "DuckDB", "pandas", "PyArrow", "lifelines"]),
    ("AI & LLM", ["Ollama", "Groq", "Google Gen AI", "scikit-learn"]),
    ("Infra", ["Docker", "Docker Compose", "uv", "pytest", "Ruff"]),
]
SEALS = {"linkedin": ("in", 17, "LinkedIn"), "email": ("@", 21, "Email")}

# The glow and flicker pattern from the design brief. The blur is the brief's 4
# on dark; on white it leaves a brown halo, so the light theme uses 2 (approved
# at design review).
NAME_GLOW_STD = {"dark": 4, "light": 2}


def glow_filter(theme: str) -> str:
    return (
        '<filter id="glow" x="-20%" y="-50%" width="140%" height="200%">'
        f'<feGaussianBlur stdDeviation="{NAME_GLOW_STD[theme]}" result="b"/>'
        '<feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>'
        "</filter>"
    )
SOFT_GLOW_FILTER = (
    '<filter id="soft-glow" x="-10%" y="-10%" width="120%" height="120%">'
    '<feGaussianBlur stdDeviation="1.5" result="b"/>'
    '<feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>'
    "</filter>"
)
FLICKER_CSS = (
    ".name { animation: flicker 6s infinite; } "
    "@keyframes flicker { 0%,91%,93%,95%,100%{opacity:1} 92%,94%{opacity:.55} }"
)


def num(v: float) -> str:
    """Compact coordinate: at most one decimal, no trailing zeros, no '-0'."""
    s = f"{v:.1f}".rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def palette(theme: str) -> dict[str, str | float]:
    t = TOKENS["themes"][theme]
    p: dict[str, str | float] = {k: v["value"] for k, v in t.items()}
    p["border_opacity"] = t["panel-border"]["opacity"]
    # Neon glow on outlines reads as glow on dark panels but as a smudge on
    # white, so the outline glow (not the name's glow) is dark-theme only.
    p["outline_filter"] = ' filter="url(#soft-glow)"' if theme == "dark" else ""
    return p


class Outliner:
    """Lays out a string glyph by glyph (advance widths only) and emits outlines."""

    def __init__(self, path: Path):
        self.file = path
        self.font = TTFont(path)
        self.glyphs = self.font.getGlyphSet()
        self.cmap = self.font.getBestCmap()
        self.upm = self.font["head"].unitsPerEm
        self.hmtx = self.font["hmtx"]

    def _glyph(self, ch: str) -> str:
        if ord(ch) not in self.cmap:
            raise SystemExit(f"{self.file.name}: no glyph for {ch!r}")
        return self.cmap[ord(ch)]

    def width(self, text: str, size: float) -> float:
        return sum(self.hmtx[self._glyph(c)][0] for c in text) * size / self.upm

    def _origin(self, text: str, x: float, size: float, anchor: str) -> float:
        return x - {"start": 0.0, "middle": self.width(text, size) / 2, "end": self.width(text, size)}[anchor]

    def _draw(self, pen, text, x, y, size, anchor, select=None) -> None:
        s = size / self.upm
        x0 = self._origin(text, x, size, anchor)
        cursor = 0
        for i, ch in enumerate(text):
            g = self._glyph(ch)
            if select is None or select(i, ch):
                self.glyphs[g].draw(TransformPen(pen, (s, 0, 0, -s, x0 + cursor * s, y)))
            cursor += self.hmtx[g][0]

    def path(self, text, x, y, size, anchor="start", select=None) -> str:
        pen = SVGPathPen(self.glyphs, ntos=num)
        self._draw(pen, text, x, y, size, anchor, select)
        return pen.getCommands()

    def bounds(self, text, x, y, size, anchor="start") -> tuple[float, float, float, float]:
        """Ink bounds in SVG coordinates: (left, top, right, bottom)."""
        pen = BoundsPen(self.glyphs)
        self._draw(pen, text, x, y, size, anchor)
        return pen.bounds


BLACKLETTER = Outliner(ROOT / "fonts/UnifrakturMaguntia/UnifrakturMaguntia-Book.ttf")
MONO = Outliner(ROOT / "fonts/JetBrainsMono/JetBrainsMono-Regular.ttf")


# ---------------------------------------------------------------- primitives
def document(w: int, h: int, title: str, body: str, defs: str = "", css: str = "") -> str:
    style = " ".join(s for s in (css, REDUCED_MOTION) if s)
    return (
        f'<svg xmlns="{SVG_NS}" width="{w}" height="{h}" viewBox="0 0 {w} {h}" role="img" aria-labelledby="t">\n'
        f'<title id="t">{html.escape(title)}</title>\n'
        f"<defs>{defs}</defs>\n"
        f"<style>{style}</style>\n"
        f"{body}\n"
        "</svg>\n"
    )


def panel(p, w: int, h: int, rx: int = 14) -> str:
    return (
        f'<rect x="0.5" y="0.5" width="{w - 1}" height="{h - 1}" rx="{rx}" fill="{p["panel"]}" '
        f'stroke="{p["panel-border"]}" stroke-opacity="{p["border_opacity"]}"/>'
    )


def spiral(x: float, y: float, heading_deg: float, r0: float, k: float = 0.62, quarters: int = 4) -> str:
    """Quarter-arc spiral turning clockwise on screen; each radius is k times the last."""
    return _spiral(x, y, heading_deg, r0, k, quarters, clockwise=True)


def _spiral(x, y, heading_deg, r0, k, quarters, clockwise: bool) -> str:
    """Quarter-arc spiral. In y-down screen space, multiplying a heading by i turns
    it clockwise and by -i counter-clockwise; each arc's radius is k times the last."""
    turn = 1j if clockwise else -1j
    p, u, r = complex(x, y), cmath.exp(1j * math.radians(heading_deg)), r0
    d = [f"M{num(p.real)} {num(p.imag)}"]
    for _ in range(quarters):
        nxt = p + r * turn * u + r * u
        d.append(f"A{num(r)} {num(r)} 0 0 {1 if clockwise else 0} {num(nxt.real)} {num(nxt.imag)}")
        p, u, r = nxt, u * turn, r * k
    return "".join(d)


def leaf(x: float, y: float, angle: float, length: float = 12, width: float = 7) -> str:
    half = width * 0.58
    return (
        f'<path transform="translate({num(x)} {num(y)}) rotate({num(angle)})" '
        f'd="M0 0Q{num(length / 2)} {num(-half)} {num(length)} 0Q{num(length / 2)} {num(half)} 0 0Z"/>'
    )


def lozenge(cx: float, cy: float, r: float) -> str:
    return f"M{num(cx)} {num(cy - r)}L{num(cx + r)} {num(cy)}L{num(cx)} {num(cy + r)}L{num(cx - r)} {num(cy)}Z"


def corner(p, curl: bool = True) -> str:
    """Corner motif in top-left orientation: a gold vine bracket (manuscript) that
    continues along each edge as a cyan circuit trace ending in a via pad."""
    gold, cyan, bg = p["gold"], p["cyan"], p["panel"]
    out = [f'<g fill="none" stroke="{gold}" stroke-width="1.5" stroke-linecap="round">',
           '<path d="M22 112V46Q22 22 46 22H112"/>']
    if curl:
        # A short stem from the bracket's corner into the panel, ending in an
        # inward (counter-clockwise) scroll that stays clear of the bracket.
        scroll = _spiral(38, 38, 45, 7, 0.6, 5, clockwise=False)
        out.append(f'<path d="M28 28L{scroll[1:]}"/>')
    out.append("</g>")
    out.append(f'<g fill="{gold}" fill-opacity="0.55" stroke="{gold}" stroke-width="0.75">'
               f"{leaf(70, 22, 35)}{leaf(22, 70, 55)}{leaf(92, 22, 145)}</g>")
    out.append(f'<g fill="none" stroke="{cyan}" stroke-width="1.5" stroke-opacity="0.8" stroke-linejoin="round">'
               '<path d="M112 22H170L178 30H250.5"/><path d="M22 112V124L30 132V134.5"/></g>')
    out.append(f'<g fill="{bg}" stroke="{cyan}" stroke-width="1.5">'
               '<circle cx="254" cy="30" r="3.5"/><circle cx="30" cy="138" r="3.5"/></g>')
    out.append(f'<circle cx="140" cy="22" r="1.8" fill="{cyan}"/>')
    return "".join(out)


def mirrored_corners(p, w: int, h: int, top_left_curl: bool) -> str:
    return "\n".join([
        f"<g>{corner(p, curl=top_left_curl)}</g>",
        f'<g transform="matrix(-1 0 0 1 {w} 0)">{corner(p)}</g>',
        f'<g transform="matrix(1 0 0 -1 0 {h})">{corner(p)}</g>',
        f'<g transform="matrix(-1 0 0 -1 {w} {h})">{corner(p)}</g>',
    ])


def sigil(p, x: float, y: float, size: float) -> str:
    """Illuminated initial: gold blackletter K on a rubric-tinted, double-ruled square."""
    gold, cyan, rubric = p["gold"], p["cyan"], p["rubric"]
    tint = 0.12 if p["panel"] == TOKENS["themes"]["dark"]["panel"]["value"] else 0.07
    k_size = size * 0.86
    left, top, right, bottom = BLACKLETTER.bounds("K", 0, 0, k_size)
    kx = x + size / 2 - (left + right) / 2
    ky = y + size / 2 - (top + bottom) / 2
    m = size / 2
    gems = "".join(lozenge(cx, cy, 3.5) for cx, cy in ((x + m, y), (x + size, y + m), (x + m, y + size), (x, y + m)))
    return (
        f'<rect x="{num(x)}" y="{num(y)}" width="{num(size)}" height="{num(size)}" rx="6" fill="{rubric}" '
        f'fill-opacity="{tint}" stroke="{gold}" stroke-width="1.5"/>'
        f'<rect x="{num(x + 5)}" y="{num(y + 5)}" width="{num(size - 10)}" height="{num(size - 10)}" rx="3" '
        f'fill="none" stroke="{cyan}" stroke-opacity="0.6" stroke-width="0.75"/>'
        f'<path d="{gems}" fill="{gold}"/>'
        f'<path{p["outline_filter"]} fill="{gold}" d="{BLACKLETTER.path("K", kx, ky, k_size)}"/>'
    )


# ---------------------------------------------------------------- assets
def frontispiece(theme: str) -> str:
    p = palette(theme)
    w, h = 1200, 300
    name_size, name_baseline = 100, 158
    sub_size, sub_baseline = 24, 248
    nl, nt, nr, nb = BLACKLETTER.bounds(NAME_TEXT, w / 2, name_baseline, name_size, "middle")
    sl, st, sr, sb = MONO.bounds(SUBTITLE_TEXT, w / 2, sub_baseline, sub_size, "middle")
    sig_x, sig_y, sig_size = 44, 44, 80
    # Layout guards: nothing collides with the sigil, nothing leaves the panel.
    assert nl > sig_x + sig_size + 40, f"name overlaps sigil ({nl:.0f})"
    assert nt > 20 and nb < st - 20, f"name/subtitle spacing ({nt:.0f},{nb:.0f},{st:.0f})"
    assert sl > 60 and sr < w - 60 and sb < h - 30, f"subtitle bounds ({sl:.0f},{sr:.0f},{sb:.0f})"
    rule_y = (nb + st) / 2
    rule = (
        f'<g stroke="{p["gold"]}" stroke-opacity="0.6" stroke-width="1">'
        f'<path d="M{num(w / 2 - 180)} {num(rule_y)}H{num(w / 2 - 14)}M{num(w / 2 + 14)} {num(rule_y)}H{num(w / 2 + 180)}"/></g>'
        f'<path d="{lozenge(w / 2, rule_y, 6)}" fill="{p["rubric"]}"/>'
        f'<g fill="{p["cyan"]}"><circle cx="{num(w / 2 - 184)}" cy="{num(rule_y)}" r="2"/>'
        f'<circle cx="{num(w / 2 + 184)}" cy="{num(rule_y)}" r="2"/></g>'
    )
    name = BLACKLETTER.path(NAME_TEXT, w / 2, name_baseline, name_size, "middle")
    words = MONO.path(SUBTITLE_TEXT, w / 2, sub_baseline, sub_size, "middle", lambda i, c: c != "·")
    dots = MONO.path(SUBTITLE_TEXT, w / 2, sub_baseline, sub_size, "middle", lambda i, c: c == "·")
    body = "\n".join([
        panel(p, w, h),
        mirrored_corners(p, w, h, top_left_curl=False),
        sigil(p, sig_x, sig_y, sig_size),
        f'<g class="name" filter="url(#glow)"><path fill="{p["gold"]}" d="{name}"/></g>',
        rule,
        f'<path fill="{p["ink"]}" d="{words}"/>',
        f'<path fill="{p["gold"]}" d="{dots}"/>',
    ])
    return document(w, h, f"{NAME_TEXT} — {SUBTITLE_TEXT}", body, glow_filter(theme) + SOFT_GLOW_FILTER, FLICKER_CSS)


def _shield(cx: float, top: float, half_w: float, side_bottom: float, tip: float) -> str:
    left, right, dh = cx - half_w, cx + half_w, tip - side_bottom
    return (
        f"M{num(left)} {num(top)}H{num(right)}V{num(side_bottom)}"
        f"C{num(right)} {num(side_bottom + dh * 0.55)} {num(cx + half_w * 0.45)} {num(tip - dh * 0.18)} {num(cx)} {num(tip)}"
        f"C{num(cx - half_w * 0.45)} {num(tip - dh * 0.18)} {num(left)} {num(side_bottom + dh * 0.55)} {num(left)} {num(side_bottom)}Z"
    )


def _shield_half_width(y: float, half_w: float, side_bottom: float, tip: float) -> float:
    """Half-width of the shield at height y (samples the lower Bezier curve)."""
    if y <= side_bottom:
        return half_w
    dh = tip - side_bottom
    p0, p1, p2, p3 = (half_w, side_bottom), (half_w, side_bottom + dh * 0.55), (half_w * 0.45, tip - dh * 0.18), (0.0, tip)
    best = 0.0
    for i in range(1001):
        t = i / 1000
        by = (1 - t) ** 3 * p0[1] + 3 * (1 - t) ** 2 * t * p1[1] + 3 * (1 - t) * t ** 2 * p2[1] + t ** 3 * p3[1]
        if by >= y:
            best = (1 - t) ** 3 * p0[0] + 3 * (1 - t) ** 2 * t * p1[0] + 3 * (1 - t) * t ** 2 * p2[0] + t ** 3 * p3[0]
            break
    return best


def armory(theme: str) -> str:
    p = palette(theme)
    w, h = 1200, 260
    col_w, half_w, top, side_bottom, tip = w / len(ARMORY), 100, 16, 136, 244
    title_size, item_size, first_item, step = 17, 15, top + 66, 24
    parts = [panel(p, w, h)]
    for i, (title, items) in enumerate(ARMORY):
        cx = col_w * i + col_w / 2
        parts.append(
            f'<path{p["outline_filter"]} d="{_shield(cx, top, half_w, side_bottom, tip)}" fill="none" '
            f'stroke="{p["gold"]}" stroke-width="1.5" stroke-linejoin="round"/>'
            f'<path d="{_shield(cx, top + 6, half_w - 6, side_bottom, tip - 9)}" fill="none" '
            f'stroke="{p["gold"]}" stroke-opacity="0.35" stroke-width="0.75"/>'
            f'<g fill="{p["panel"]}" stroke="{p["cyan"]}" stroke-width="1.2">'
            f'<circle cx="{num(cx - half_w)}" cy="{top}" r="2.6"/><circle cx="{num(cx + half_w)}" cy="{top}" r="2.6"/></g>'
        )
        parts.append(f'<path fill="{p["rubric"]}" d="{MONO.path(title, cx, top + 34, title_size, "middle")}"/>')
        rule_y = top + 46
        parts.append(
            f'<path d="M{num(cx - 60)} {rule_y}H{num(cx - 8)}M{num(cx + 8)} {rule_y}H{num(cx + 60)}" '
            f'stroke="{p["gold"]}" stroke-opacity="0.5" stroke-width="1"/>'
            f'<path d="{lozenge(cx, rule_y, 3.5)}" fill="{p["gold"]}"/>'
        )
        for j, item in enumerate(items):
            baseline = first_item + j * step
            il, it, ir, ib = MONO.bounds(item, cx, baseline, item_size, "middle")
            room = _shield_half_width(ib, half_w - 6, side_bottom, tip - 9)
            assert (ir - il) / 2 + 8 <= room, f"{item!r} does not fit its shield ({(ir - il) / 2:.0f} > {room - 8:.0f})"
            parts.append(f'<path fill="{p["ink"]}" d="{MONO.path(item, cx, baseline, item_size, "middle")}"/>')
        # Column number as a Roman numeral, set in the shield's otherwise empty base.
        numeral = ("I", "II", "III", "IV", "V")[i]
        parts.append(f'<path fill="{p["muted"]}" d="{MONO.path(numeral, cx, 214, 14, "middle")}"/>')
    title ="Tech stack — " + "; ".join(f"{t}: {', '.join(items)}" for t, items in ARMORY)
    return document(w, h, title, "\n".join(parts), SOFT_GLOW_FILTER)


def seal(theme: str, kind: str) -> str:
    p = palette(theme)
    glyph, size, label = SEALS[kind]
    w = h = 48
    c, r_out, r_in = 24, 19, 15

    def hexagon(r: float) -> str:
        pts = [(c + r * math.cos(math.radians(-90 + 60 * k)), c + r * math.sin(math.radians(-90 + 60 * k))) for k in range(6)]
        return "M" + "L".join(f"{num(x)} {num(y)}" for x, y in pts) + "Z"

    defs = (
        '<linearGradient id="holo" gradientUnits="userSpaceOnUse" x1="6" y1="6" x2="42" y2="42">'
        f'<stop offset="0" stop-color="{p["cyan"]}"/><stop offset="0.5" stop-color="{p["rubric"]}"/>'
        f'<stop offset="1" stop-color="{p["gold"]}"/></linearGradient>'
    )
    gl, gt, gr, gb = MONO.bounds(glyph, 0, 0, size)
    gx, gy = c - (gl + gr) / 2, c - (gt + gb) / 2
    body = "\n".join([
        panel(p, w, h, rx=10),
        f'<path d="{hexagon(r_out)}" fill="url(#holo)" fill-opacity="0.16" stroke="url(#holo)" stroke-width="2" stroke-linejoin="round"/>',
        f'<path d="{hexagon(r_in)}" fill="none" stroke="{p["gold"]}" stroke-opacity="0.5" stroke-width="0.75"/>',
        f'<path fill="{p["ink"]}" d="{MONO.path(glyph, gx, gy, size)}"/>',
    ])
    return document(w, h, label, body, defs)


def tapestry_placeholder(theme: str) -> str:
    """Stand-in for the contribution snake until the first workflow run replaces it."""
    p = palette(theme)
    w, h = 1200, 240
    cell, gap, weeks, days = 12, 3, 53, 7
    x0 = (w - (weeks * (cell + gap) - gap)) / 2
    y0 = 36
    cells = "".join(
        f'<rect x="{num(x0 + wk * (cell + gap))}" y="{y0 + d * (cell + gap)}" width="{cell}" height="{cell}" rx="2"/>'
        for wk in range(weeks) for d in range(days))
    body = "\n".join([
        panel(p, w, h),
        f'<g fill="{TOKENS["tapestry"][theme]["dots"][0]}">{cells}</g>',
        f'<path fill="{p["gold"]}" d="{MONO.path("The loom is warming up", w / 2, 180, 20, "middle")}"/>',
        f'<path fill="{p["muted"]}" d="{MONO.path("Contribution graph appears after the first daily run", w / 2, 210, 14, "middle")}"/>',
    ])
    return document(w, h, "Contribution graph placeholder: the loom is warming up", body)


def write_placeholders() -> list[Path]:
    """Write dist/tapestry-{dark,light}.svg only where no file exists yet (never
    overwrite the workflow's real output)."""
    dist = ROOT / "dist"
    dist.mkdir(exist_ok=True)
    written = []
    for theme in THEMES:
        path = dist / f"tapestry-{theme}.svg"
        if not path.exists():
            path.write_text(tapestry_placeholder(theme), encoding="utf-8")
            written.append(path)
    return written


def build() -> list[Path]:
    ASSETS.mkdir(exist_ok=True)
    written = []
    for theme in THEMES:
        outputs = {
            f"frontispiece-{theme}.svg": frontispiece(theme),
            f"armory-{theme}.svg": armory(theme),
            **{f"seal-{kind}-{theme}.svg": seal(theme, kind) for kind in SEALS},
        }
        for name, svg in outputs.items():
            path = ASSETS / name
            path.write_text(svg, encoding="utf-8")
            written.append(path)
    return written


# ---------------------------------------------------------------- validation
def _luminance(hex_colour: str) -> float:
    r, g, b = (int(hex_colour.lstrip("#")[i:i + 2], 16) / 255 for i in (0, 2, 4))
    f = lambda c: c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4  # noqa: E731
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


def _contrast(a: str, b: str) -> float:
    hi, lo = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def _blend(fg: str, bg: str, alpha: float) -> str:
    f = [int(fg.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)]
    b = [int(bg.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)]
    return "#" + "".join(f"{round(alpha * x + (1 - alpha) * y):02X}" for x, y in zip(f, b))


def contrast_checks() -> list[tuple[str, float]]:
    """Text drawn on a tinted fill rather than the bare panel: recheck AA (4.5:1)."""
    rows = []
    for theme in THEMES:
        p = palette(theme)
        tint = 0.12 if theme == "dark" else 0.07
        rows.append((f"{theme}: sigil K (gold) on rubric tint", _contrast(p["gold"], _blend(p["rubric"], p["panel"], tint))))
        for stop in ("cyan", "rubric", "gold"):
            rows.append((f"{theme}: seal glyph (ink) on {stop} 16% tint",
                         _contrast(p["ink"], _blend(p[stop], p["panel"], 0.16))))
        for key in ("ink", "gold", "rubric", "cyan", "muted"):
            rows.append((f"{theme}: {key} on panel", _contrast(p[key], p["panel"])))
    return rows


def validate(paths: list[Path]) -> bool:
    import cairosvg  # imported here so a plain build does not need it

    ok = True
    print(f"{'file':34} {'bytes':>7} {'xmllint':8} {'etree':6} {'ext-url':8} {'motion':7} {'png':10}")
    for path in sorted(paths):
        data = path.read_bytes()
        xml_ok = subprocess.run(["xmllint", "--noout", str(path)], capture_output=True).returncode == 0
        try:
            ET.fromstring(data)
            etree_ok = True
        except ET.ParseError:
            etree_ok = False
        external = re.findall(rb"https?://", re.sub(rb'\sxmlns(?::\w+)?="[^"]*"', b"", data))
        motion_ok = REDUCED_MOTION.encode() in data
        try:
            png = cairosvg.svg2png(bytestring=data)
            pw, ph = struct.unpack(">II", png[16:24])
            png_res = f"{pw}x{ph}"
        except Exception as exc:  # noqa: BLE001 - report any renderer failure
            png_res = f"FAIL {type(exc).__name__}"
        size_ok = len(data) <= MAX_BYTES
        row_ok = xml_ok and etree_ok and not external and motion_ok and size_ok and not png_res.startswith("FAIL")
        ok &= row_ok
        print(f"{path.name:34} {len(data):7d} {'ok' if xml_ok else 'FAIL':8} {'ok' if etree_ok else 'FAIL':6} "
              f"{'none' if not external else len(external):<8} {'ok' if motion_ok else 'FAIL':7} {png_res:10}"
              f"{'' if size_ok else '  OVER 150 KB'}")
    print("\ncontrast (WCAG AA needs >= 4.5):")
    for label, ratio in contrast_checks():
        ok &= ratio >= 4.5
        print(f"  {label:44} {ratio:5.2f} {'ok' if ratio >= 4.5 else 'FAIL'}")
    return ok


# ---------------------------------------------------------------- preview
def write_preview() -> Path:
    """Self-contained review page (SVGs inlined as data URIs). Git-ignored."""
    files = sorted(ASSETS.glob("*.svg")) + sorted((ROOT / "dist").glob("*.svg"))

    def uri(path: Path) -> str:
        return "data:image/svg+xml;base64," + base64.b64encode(path.read_bytes()).decode()

    backgrounds = [("#0D1117", "GitHub dark"), ("#22272E", "GitHub dark dimmed (approx.)"), ("#FFFFFF", "GitHub light")]
    rows = []
    for f in files:
        width = "48" if f.name.startswith("seal-") else "100%"
        cells = "".join(
            f'<figure style="background:{bg}"><img src="{uri(f)}" width="{width}" alt="{html.escape(f.name)}">'
            f'<figcaption>{label} {bg}</figcaption></figure>' for bg, label in backgrounds)
        rows.append(f"<section><h2>{html.escape(f.relative_to(ROOT).as_posix())}</h2><div class=row>{cells}</div></section>")

    def column(theme: str, bg: str) -> str:
        order = ["frontispiece", "armory", "chronicle", "tapestry"]
        imgs = []
        for stem in order:
            for folder in (ASSETS, ROOT / "dist"):
                f = folder / f"{stem}-{theme}.svg"
                if f.exists():
                    imgs.append(f'<img src="{uri(f)}" width="100%" alt="{stem}">')
        seals = "".join(f'<img src="{uri(ASSETS / f"seal-{k}-{theme}.svg")}" width="48" alt="{k}"> ' for k in SEALS)
        return f'<div class=mobile style="background:{bg}"><p>{theme} · 375 px</p>{"".join(imgs)}<div class=seals>{seals}</div></div>'

    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Asset preview</title>
<style>
  body {{ margin: 0; padding: 16px; font: 14px/1.4 system-ui, sans-serif; background: #F6F8FA; color: #1F2328; }}
  h1 {{ font-size: 20px; }} h2 {{ font-size: 15px; margin: 24px 0 8px; font-family: ui-monospace, monospace; }}
  .row {{ display: grid; grid-template-columns: 1fr; gap: 8px; }}
  figure {{ margin: 0; padding: 16px; border: 1px solid #D0D7DE; border-radius: 6px; }}
  figcaption {{ font-size: 12px; color: #8B949E; margin-top: 6px; }}
  .cols {{ display: flex; gap: 16px; flex-wrap: wrap; }}
  .mobile {{ width: 375px; box-sizing: border-box; padding: 16px; border: 1px solid #D0D7DE; border-radius: 6px; }}
  .mobile > img {{ display: block; margin-bottom: 12px; }} .seals img {{ display: inline-block; margin-right: 8px; }} .mobile p {{ color: #8B949E; margin: 0 0 8px; }}
</style></head><body>
<h1>Asset preview</h1>
<h2>375 px column (README order)</h2>
<div class=cols>{column("dark", "#0D1117")}{column("dark", "#22272E")}{column("light", "#FFFFFF")}</div>
{"".join(rows)}
</body></html>
"""
    out = ROOT / "preview" / "index.html"
    out.parent.mkdir(exist_ok=True)
    out.write_text(page, encoding="utf-8")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="validate every SVG after building")
    ap.add_argument("--preview", action="store_true", help="write preview/index.html")
    ap.add_argument("--placeholders", action="store_true",
                    help="write dist/tapestry-{dark,light}.svg placeholders if they do not exist")
    args = ap.parse_args()
    written = build()
    print(f"wrote {len(written)} SVGs to {ASSETS.relative_to(ROOT)}/")
    if args.placeholders:
        placeholders = write_placeholders()
        print(f"wrote {len(placeholders)} placeholder(s) to dist/")
        written += placeholders
    ok = validate(written) if args.check else True
    if args.preview:
        print(f"wrote {write_preview().relative_to(ROOT)}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
