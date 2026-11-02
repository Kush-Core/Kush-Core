#!/usr/bin/env python3
"""Repo-level theming for the pinned projects: social previews and README header strips.

    python tools/build_repo_theming.py social          # social/<repo>-preview.svg (dark, 1280x640)
    python tools/build_repo_theming.py headers OUT_DIR # OUT_DIR/<repo>/assets/header-{dark,light}.svg (1200x120)

The social SVGs are rasterised to PNG separately (a browser is needed for the
glow filter); social/ is git-ignored. Descriptions come from each repo's README
as confirmed in the repo audit.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_assets as ba  # noqa: E402
import content  # noqa: E402

PROJECTS = content.PROJECTS
num = ba.num


def _chips(p, labels: list[str], cy: float, size: float, cx: float) -> str:
    pad, gap, h = 18, 16, size * 1.9
    widths = [ba.MONO.width(t, size) + 2 * pad for t in labels]
    x = cx - (sum(widths) + gap * (len(widths) - 1)) / 2
    out = []
    for text, w in zip(labels, widths):
        out.append(
            f'<rect x="{num(x)}" y="{num(cy - h / 2)}" width="{num(w)}" height="{num(h)}" rx="{num(h / 2)}" '
            f'fill="{p["cyan"]}" fill-opacity="0.08" stroke="{p["cyan"]}" stroke-width="1.5"/>'
            f'<path fill="{p["ink"]}" d="{ba.MONO.path(text, x + w / 2, cy + size * 0.36, size, "middle")}"/>'
        )
        x += w + gap
    return "".join(out)


def social(repo: str) -> str:
    spec, p = PROJECTS[repo], ba.palette("dark")
    w, h, cx = 1280, 640, 640
    line_size, margin = 24, 80
    assert ba.MONO.width(spec["line"], line_size) <= w - 2 * margin, f"{repo}: description too wide"
    nl, nt, nr, nb = ba.BLACKLETTER.bounds(spec["name"], cx, 300, 132, "middle")
    assert nl > 52 + 96 + 30 and nr < w - 60, f"{repo}: name too wide"
    rule_y = 362
    chips_y = 520 if spec["chip_label"] else 500
    body = [
        f'<rect width="{w}" height="{h}" fill="{p["panel"]}"/>',
        ba.mirrored_corners(p, w, h, top_left_curl=False),
        ba.sigil(p, 52, 52, 96),
        f'<g filter="url(#glow)"><path fill="{p["gold"]}" d="{ba.BLACKLETTER.path(spec["name"], cx, 300, 132, "middle")}"/></g>',
        f'<path d="M{cx - 200} {rule_y}H{cx - 16}M{cx + 16} {rule_y}H{cx + 200}" stroke="{p["gold"]}" stroke-opacity="0.6"/>'
        f'<path d="{ba.lozenge(cx, rule_y, 7)}" fill="{p["rubric"]}"/>',
        f'<path fill="{p["ink"]}" d="{ba.MONO.path(spec["line"], cx, 422, line_size, "middle")}"/>',
    ]
    if spec["chip_label"]:
        body.append(f'<path fill="{p["muted"]}" d="{ba.MONO.path(spec["chip_label"], cx, 476, 18, "middle")}"/>')
    body.append(_chips(p, spec["chips"], chips_y, 20, cx))
    body.append(f'<path fill="{p["muted"]}" d="{ba.MONO.path(f"github.com/Kush-Core/{repo}", cx, 596, 18, "middle")}"/>')
    return ba.document(w, h, f"{spec['name']} — {spec['line']}", "\n".join(body),
                       ba.glow_filter("dark") + ba.SOFT_GLOW_FILTER)


def header(repo: str, theme: str) -> str:
    spec, p = PROJECTS[repo], ba.palette(theme)
    w, h = 1200, 120
    name_x, line_size = 120, 16
    nl, nt, nr, nb = ba.BLACKLETTER.bounds(spec["name"], name_x, 64, 54)
    ll, lt, lr, lb = ba.MONO.bounds(spec["line"], name_x + 2, 98, line_size)
    assert max(nr, lr) < 930, f"{repo}: header text runs into the ornament ({max(nr, lr):.0f})"
    assert nt > 8 and lb < h - 8, f"{repo}: header text leaves the panel"
    gold, cyan = p["gold"], p["cyan"]
    ornament = (
        f'<g fill="none" stroke="{cyan}" stroke-width="1.5" stroke-opacity="0.8" stroke-linejoin="round">'
        f'<path d="M953.5 60H1010L1020 50H1080"/></g>'
        f'<circle cx="950" cy="60" r="3.5" fill="{p["panel"]}" stroke="{cyan}" stroke-width="1.5"/>'
        f'<circle cx="1000" cy="60" r="1.8" fill="{cyan}"/>'
        f'<g fill="none" stroke="{gold}" stroke-width="1.5" stroke-linecap="round">'
        f'<path d="M1080 50H1130{ba._spiral(1130, 50, 0, 12, 0.6, 5, clockwise=True)[len("M1130 50"):]}"/></g>'
        f'<g fill="{gold}" fill-opacity="0.55" stroke="{gold}" stroke-width="0.75">'
        f'{ba.leaf(1095, 50, 35)}{ba.leaf(1112, 50, -35)}</g>'
    )
    body = [
        ba.panel(p, w, h, rx=12),
        ba.sigil(p, 24, 24, 72),
        f'<g{p["outline_filter"]}><path fill="{gold}" d="{ba.BLACKLETTER.path(spec["name"], name_x, 64, 54)}"/></g>',
        f'<path fill="{p["ink"]}" d="{ba.MONO.path(spec["line"], name_x + 2, 98, line_size)}"/>',
        ornament,
    ]
    return ba.document(w, h, f"{spec['name']} — {spec['line']}", "\n".join(body), ba.SOFT_GLOW_FILTER)


def main(argv: list[str]) -> int:
    if argv[:1] == ["social"]:
        out = ba.ROOT / "social"
        out.mkdir(exist_ok=True)
        for repo in PROJECTS:
            path = out / f"{repo}-preview.svg"
            path.write_text(social(repo), encoding="utf-8")
            print(f"wrote {path.relative_to(ba.ROOT)}")
        return 0
    if argv[:1] == ["headers"] and len(argv) == 2:
        for repo in PROJECTS:
            folder = Path(argv[1]) / repo / "assets"
            folder.mkdir(parents=True, exist_ok=True)
            paths = []
            for theme in ba.THEMES:
                path = folder / f"header-{theme}.svg"
                path.write_text(header(repo, theme), encoding="utf-8")
                paths.append(path)
            print(f"wrote {', '.join(str(p) for p in paths)}")
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
