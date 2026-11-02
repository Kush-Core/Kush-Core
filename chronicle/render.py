"""Render the Chronicle: recent public GitHub activity as a terminal-style SVG.

    python -m chronicle.render --user Kush-Core --out dist          # fetch + render
    python -m chronicle.render --user Kush-Core --out dist --empty  # no-activity state

Writes dist/chronicle-{dark,light}.svg. If the API answers 403/429/5xx or the
network fails, existing files are left untouched and the exit code is 0.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import tempfile
from datetime import timedelta, timezone
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from chronicle import fetch
from chronicle.roman import roman_date

ROOT = Path(__file__).resolve().parent.parent
TOKENS = json.loads((ROOT / "tokens.json").read_text(encoding="utf-8"))
FONT = ROOT / "fonts" / "jbm-ascii.woff2"

# Code points present in fonts/jbm-ascii.woff2; anything else becomes "?".
SUBSET = frozenset(range(0x20, 0x7F)) | {0xB7, 0x2192, 0x25B8}
MAX_MESSAGE = 60
MAX_REPO = 22
WIDTH, HEIGHT = 1200, 240
BLINK_S = 1.4  # cursor period; the brief requires >= 1.2 s
DISPLAY_TZ = timezone(timedelta(hours=5, minutes=30), "IST")  # dates shown in Indian Standard Time

LABELS = {"pr_opened": "petitioned", "pr_merged": "sealed", "release": "proclaimed", "founded": "founded"}

_env = Environment(
    loader=FileSystemLoader(Path(__file__).resolve().parent / "templates"),
    autoescape=True,  # commit messages and titles are untrusted text
    undefined=StrictUndefined,
    keep_trailing_newline=True,
)


def clean(text: str | None, limit: int) -> str:
    """First line only, characters outside the font subset replaced by '?',
    at most ``limit`` characters (a cut ends in '...')."""
    lines = (text or "").splitlines()
    first = lines[0].replace("\t", " ").strip() if lines else ""
    safe = "".join(ch if ord(ch) in SUBSET else "?" for ch in first)
    return safe if len(safe) <= limit else safe[: limit - 3] + "..."


def label(entry: fetch.Entry) -> str:
    if entry.kind == "push":
        if entry.count is None:
            return "forged commits"
        return f"forged {entry.count} commit{'' if entry.count == 1 else 's'}"
    return LABELS[entry.kind]


def _repo_name(repo: str, user: str) -> str:
    owner, _, name = repo.partition("/")
    return name if name and owner.lower() == user.lower() else repo


def _colours(theme: str) -> dict:
    t = TOKENS["themes"][theme]
    return {
        **{k: t[k]["value"] for k in ("ink", "gold", "rubric", "cyan", "muted", "panel")},
        "border": t["panel-border"]["value"],
        "border_opacity": t["panel-border"]["opacity"],
    }


def render(entries: list[fetch.Entry], user: str, theme: str) -> str:
    rows = [
        {
            "date": roman_date(e.when.astimezone(DISPLAY_TZ).date()),
            "repo": clean(_repo_name(e.repo, user), MAX_REPO),
            "label": label(e),
            "message": clean(e.message, MAX_MESSAGE),
        }
        for e in entries
    ]
    return _env.get_template("chronicle.svg.j2").render(
        width=WIDTH,
        height=HEIGHT,
        title=f"Chronicle: the {len(rows)} most recent public GitHub events of {user}" if rows
        else f"Chronicle: no recent public GitHub events for {user}",
        rows=rows,
        c=_colours(theme),
        font_b64=base64.b64encode(FONT.read_bytes()).decode("ascii"),
        blink_s=BLINK_S,
        reduced_motion=TOKENS["motion"]["reduced_motion_css"],
    )


def write(entries: list[fetch.Entry], user: str, out: Path) -> list[Path]:
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for theme in ("dark", "light"):
        target = out / f"chronicle-{theme}.svg"
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=out, delete=False, suffix=".tmp") as tmp:
            tmp.write(render(entries, user, theme))
        os.chmod(tmp.name, 0o644)  # NamedTemporaryFile creates 0600
        os.replace(tmp.name, target)  # atomic: a reader never sees a half-written file
        written.append(target)
    return written


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Render the Chronicle SVGs.")
    ap.add_argument("--user", required=True, help="GitHub login whose public events are shown")
    ap.add_argument("--out", type=Path, required=True, help="output directory, e.g. dist")
    ap.add_argument("--empty", action="store_true", help="render the no-activity state without calling the API")
    args = ap.parse_args(argv)

    if args.empty:
        entries: list[fetch.Entry] = []
    else:
        token = os.environ.get("GITHUB_TOKEN") or None
        try:
            entries = fetch.select(fetch.fetch_events(args.user, token), token)
        except fetch.FetchError as exc:
            if exc.keep_previous:
                print(f"chronicle: GitHub API unavailable ({exc}); kept existing files in {args.out}/", file=sys.stderr)
                return 0
            raise
    for path in write(entries, args.user, args.out):
        print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
