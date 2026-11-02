"""Quests Abroad: merged pull requests to other people's public repositories.

    python -m chronicle.quests --user Kush-Core --out dist --readme README.md

Searches GitHub for merged, public pull requests the user authored in
repositories the user does not own, renders dist/quests-{dark,light}.svg and
rewrites the README between the quests markers. With no qualifying pull
requests the section is removed (hidden) until one exists. On 403/429/5xx or a
network failure nothing is changed and the exit code is 0.

Entries can be hidden with contributions.json: {"exclude": ["owner/repo#123", "owner/repo"]}.
"""

from __future__ import annotations

import argparse
import base64
import html
import json
import os
import re
import sys
import tempfile
import urllib.parse
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from chronicle import fetch, render
from chronicle.roman import roman_date

LIMIT = 6
MAX_REPO = 24
MAX_TITLE = 60
START, END = "<!-- quests:start -->", "<!-- quests:end -->"
HEADING = "### ✠ Quests Abroad · Open Source Contributions"
CONFIG = render.ROOT / "contributions.json"


@dataclass(frozen=True)
class Quest:
    repo: str          # owner/name of the upstream repository
    number: int
    title: str         # untrusted text
    url: str           # https://github.com/... link to the pull request
    merged: datetime


def search_query(user: str) -> str:
    return f"type:pr author:{user} is:public is:merged -user:{user}"


def api_search_url(user: str) -> str:
    return f"{fetch.API}/search/issues?q={urllib.parse.quote(search_query(user))}&sort=updated&order=desc&per_page=100"


def web_search_url(user: str) -> str:
    return "https://github.com/search?" + urllib.parse.urlencode({"q": search_query(user), "type": "pullrequests"})


def load_excludes(path: Path = CONFIG) -> frozenset[str]:
    if not path.exists():
        return frozenset()
    data = json.loads(path.read_text(encoding="utf-8"))
    return frozenset(str(item).lower() for item in data.get("exclude", []))


def fetch_quests(user: str, token: str | None, get=None, excludes: frozenset[str] = frozenset()) -> list[Quest]:
    """All qualifying pull requests, most recently merged first."""
    get = get or fetch._get  # looked up at call time so tests can patch fetch._get
    data = get(api_search_url(user), token)
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        raise fetch.FetchError(None, "unexpected search response shape")
    quests = []
    for item in data["items"]:
        if not isinstance(item, dict):
            continue
        merged_at = (item.get("pull_request") or {}).get("merged_at")
        match = re.fullmatch(r"https://api\.github\.com/repos/([^/]+)/([^/]+)", str(item.get("repository_url", "")))
        number, url = item.get("number"), str(item.get("html_url", ""))
        if not (merged_at and match and isinstance(number, int) and url.startswith("https://github.com/")):
            continue
        owner, name = match.groups()
        repo = f"{owner}/{name}"
        if owner.lower() == user.lower():  # the search already excludes these; defend anyway
            continue
        if repo.lower() in excludes or f"{repo}#{number}".lower() in excludes:
            continue
        try:
            merged = datetime.fromisoformat(str(merged_at).replace("Z", "+00:00"))
        except ValueError:
            continue
        quests.append(Quest(repo, number, str(item.get("title") or f"#{number}"), url, merged))
    quests.sort(key=lambda q: q.merged, reverse=True)
    return quests


def _summary(quests: list[Quest]) -> str:
    repos = len({q.repo.lower() for q in quests})
    return (f"{len(quests)} merged pull request{'' if len(quests) == 1 else 's'} "
            f"across {repos} repositor{'y' if repos == 1 else 'ies'}")


def render_svg(quests: list[Quest], user: str, theme: str) -> str:
    shown = quests[:LIMIT]
    rows = [{
        "date": roman_date(q.merged.astimezone(render.DISPLAY_TZ).date()),
        "repo": render.clean(q.repo, MAX_REPO),
        "label": render.clean(f"sealed #{q.number}", 14),
        "title": render.clean(q.title, MAX_TITLE),
    } for q in shown]
    summary_y = 91 + 25 * len(rows) + 8
    prompt_y = summary_y + 25
    return render._env.get_template("quests.svg.j2").render(
        width=render.WIDTH,
        height=prompt_y + 24,
        title=f"Quests Abroad: merged open-source pull requests by {user}",
        rows=rows,
        summary=render.clean(_summary(quests), 80),
        summary_y=summary_y,
        prompt_y=prompt_y,
        c=render._colours(theme),
        font_b64=base64.b64encode(render.FONT.read_bytes()).decode("ascii"),
        blink_s=render.BLINK_S,
        reduced_motion=render.TOKENS["motion"]["reduced_motion_css"],
    )


def section(quests: list[Quest], user: str) -> str:
    """README block between the markers; empty when there is nothing to show."""
    if not quests:
        return ""
    raw = f"https://raw.githubusercontent.com/{user}/{user}/main/dist"
    alt = "Merged pull requests to other open-source projects: " + "; ".join(
        f"{q.repo} #{q.number}: {' '.join(q.title.split())}" for q in quests[:LIMIT])
    return (
        f"{HEADING}\n\n"
        f'<a href="{html.escape(web_search_url(user), quote=True)}"><picture>'
        f'<source media="(prefers-color-scheme: dark)" srcset="{raw}/quests-dark.svg">'
        f'<img width="100%" alt="{html.escape(alt, quote=True)}" src="{raw}/quests-light.svg">'
        f"</picture></a>\n"
    )


def update_readme(text: str, block: str) -> str:
    if text.count(START) != 1 or text.count(END) != 1 or text.index(START) > text.index(END):
        raise SystemExit(f"README must contain exactly one {START} followed by one {END}")
    before, rest = text.split(START, 1)
    _, after = rest.split(END, 1)
    inner = f"\n{block}" if block else "\n"
    return f"{before}{START}{inner}{END}{after}"


def _write_atomic(path: Path, content: str) -> None:
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False, suffix=".tmp") as tmp:
        tmp.write(content)
    os.chmod(tmp.name, 0o644)
    os.replace(tmp.name, path)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Render the Quests Abroad card and README section.")
    ap.add_argument("--user", required=True)
    ap.add_argument("--out", type=Path, required=True, help="output directory, e.g. dist")
    ap.add_argument("--readme", type=Path, required=True)
    ap.add_argument("--config", type=Path, default=CONFIG, help="JSON file with an 'exclude' list")
    args = ap.parse_args(argv)

    readme = args.readme.read_text(encoding="utf-8")
    token = os.environ.get("GITHUB_TOKEN") or None
    try:
        quests = fetch_quests(args.user, token, excludes=load_excludes(args.config))
    except fetch.FetchError as exc:
        if exc.keep_previous:
            print(f"quests: GitHub API unavailable ({exc}); kept README and {args.out}/ unchanged", file=sys.stderr)
            return 0
        raise

    args.out.mkdir(parents=True, exist_ok=True)
    for theme in ("dark", "light"):
        target = args.out / f"quests-{theme}.svg"
        if quests:
            _write_atomic(target, render_svg(quests, args.user, theme))
        elif target.exists():
            target.unlink()  # section hidden: do not leave a stale card behind
    new_readme = update_readme(readme, section(quests, args.user))
    if new_readme != readme:
        _write_atomic(args.readme, new_readme)
    print(f"quests: {len(quests)} merged pull request(s); section {'shown' if quests else 'hidden'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
