import json
import re
import urllib.parse
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from chronicle import fetch, quests

ROOT = Path(__file__).resolve().parents[2]
USER = "Kush-Core"


def item(repo, number, title, merged_at="2026-10-30T10:00:00Z", url=None):
    return {
        "number": number,
        "title": title,
        "html_url": url or f"https://github.com/{repo}/pull/{number}",
        "repository_url": f"https://api.github.com/repos/{repo}",
        "pull_request": {"merged_at": merged_at},
    }


SEARCH = {"total_count": 6, "incomplete_results": False, "items": [
    item("memgraph/ai-toolkit", 576, "lightrag-memgraph: get_docs_paginated breaks ties by id", "2026-10-30T10:00:00Z"),
    item("other/lib", 12, "<script>&\"quoted\"", "2026-11-01T10:00:00Z"),
    item("other/lib", 13, "not merged", None),
    item("Kush-Core/hubahu", 1, "own repository", "2026-11-02T10:00:00Z"),
    item("hidden/repo", 7, "excluded by repo", "2026-10-01T10:00:00Z"),
    item("evil/link", 1, "bad url", "2026-10-02T10:00:00Z", url="https://evil.example/x"),
]}


def readme_with_markers(inner="\n"):
    return f"# Title\n\nbefore\n\n{quests.START}{inner}{quests.END}\n\nafter\n"


# ------------------------------------------------------------------ search
def test_search_query_and_urls():
    q = quests.search_query(USER)
    for part in ("type:pr", "author:Kush-Core", "is:public", "is:merged", "-user:Kush-Core"):
        assert part in q
    api = quests.api_search_url(USER)
    assert api.startswith("https://api.github.com/search/issues?q=")
    assert urllib.parse.unquote(api.split("q=", 1)[1].split("&", 1)[0]) == q
    assert quests.web_search_url(USER).startswith("https://github.com/search?")


def test_fetch_filters_and_sorts():
    found = quests.fetch_quests(USER, None, get=lambda url, token: SEARCH, excludes=frozenset({"hidden/repo"}))
    assert [(q.repo, q.number) for q in found] == [("other/lib", 12), ("memgraph/ai-toolkit", 576)]


def test_exclude_single_pull_request():
    found = quests.fetch_quests(USER, None, get=lambda url, token: SEARCH, excludes=frozenset({"other/lib#12"}))
    assert ("other/lib", 12) not in [(q.repo, q.number) for q in found]


def test_unexpected_shape_is_an_error():
    with pytest.raises(fetch.FetchError):
        quests.fetch_quests(USER, None, get=lambda url, token: [])


# ------------------------------------------------------------------ SVG
def test_svg_escapes_parses_and_is_self_contained():
    found = quests.fetch_quests(USER, None, get=lambda url, token: SEARCH)
    for theme in ("dark", "light"):
        svg = quests.render_svg(found, USER, theme)
        ET.fromstring(svg)
        assert "<script" not in svg and "&lt;script&gt;&amp;" in svg
        assert not re.search(r"https?://", re.sub(r'\sxmlns(?::\w+)?="[^"]*"', "", svg))
        assert len(svg.encode()) <= 100_000
        assert "quests.log" in svg and "sealed #576" in svg
        assert "3 merged pull requests across 3 repositories" in svg


def test_svg_shows_at_most_six_rows_but_counts_all():
    many = {"items": [item(f"org/r{i}", i, f"pr {i}", f"2026-10-{i + 1:02d}T00:00:00Z") for i in range(9)]}
    found = quests.fetch_quests(USER, None, get=lambda url, token: many)
    svg = quests.render_svg(found, USER, "dark")
    assert svg.count(">sealed #") == 6
    assert "9 merged pull requests across 9 repositories" in svg


# ------------------------------------------------------------------ README section
def test_section_shown_with_escaped_alt_and_link():
    found = quests.fetch_quests(USER, None, get=lambda url, token: SEARCH)
    block = quests.section(found, USER)
    assert block.startswith(quests.HEADING)
    assert 'href="https://github.com/search?' in block
    assert "dist/quests-dark.svg" in block and "dist/quests-light.svg" in block
    alt = re.search(r'alt="([^"]*)"', block).group(1)
    assert "&lt;script&gt;&amp;&quot;quoted&quot;" in alt and "<script" not in block


def test_readme_update_hides_when_empty_and_is_idempotent():
    text = readme_with_markers("\nold block\n")
    hidden = quests.update_readme(text, "")
    assert f"{quests.START}\n{quests.END}" in hidden and "old block" not in hidden
    shown = quests.update_readme(hidden, "### block\n")
    assert quests.update_readme(shown, "### block\n") == shown
    assert shown.startswith("# Title\n\nbefore\n\n") and shown.endswith("\n\nafter\n")


@pytest.mark.parametrize("text", ["no markers", f"{quests.END}{quests.START}", f"{quests.START}{quests.START}{quests.END}"])
def test_readme_markers_must_be_well_formed(text):
    with pytest.raises(SystemExit):
        quests.update_readme(text, "")


def test_profile_readme_has_markers():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert readme.count(quests.START) == 1 and readme.count(quests.END) == 1


def test_contributions_config_is_valid():
    data = json.loads((ROOT / "contributions.json").read_text(encoding="utf-8"))
    assert isinstance(data.get("exclude"), list)


# ------------------------------------------------------------------ end to end
def _setup(tmp_path):
    readme = tmp_path / "README.md"
    readme.write_text(readme_with_markers(), encoding="utf-8")
    out = tmp_path / "dist"
    out.mkdir()
    config = tmp_path / "contributions.json"
    config.write_text('{"exclude": []}', encoding="utf-8")
    return readme, out, config


def test_main_shows_then_hides(tmp_path, monkeypatch):
    readme, out, config = _setup(tmp_path)
    args = ["--user", USER, "--out", str(out), "--readme", str(readme), "--config", str(config)]
    monkeypatch.setattr(fetch, "_get", lambda url, token: SEARCH)
    assert quests.main(args) == 0
    assert quests.HEADING in readme.read_text(encoding="utf-8")
    assert (out / "quests-dark.svg").exists() and (out / "quests-light.svg").exists()

    monkeypatch.setattr(fetch, "_get", lambda url, token: {"items": []})
    assert quests.main(args) == 0
    assert quests.HEADING not in readme.read_text(encoding="utf-8")
    assert not (out / "quests-dark.svg").exists() and not (out / "quests-light.svg").exists()


@pytest.mark.parametrize("status", [403, 429, 500, None])
def test_temporary_failure_changes_nothing(tmp_path, monkeypatch, status):
    readme, out, config = _setup(tmp_path)
    readme.write_text(quests.update_readme(readme.read_text(encoding="utf-8"), "### kept\n"), encoding="utf-8")
    card = out / "quests-dark.svg"
    card.write_text("previous", encoding="utf-8")
    before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in (readme, card)}

    def failing(url, token):
        raise fetch.FetchError(status, "simulated")

    monkeypatch.setattr(fetch, "_get", failing)
    assert quests.main(["--user", USER, "--out", str(out), "--readme", str(readme), "--config", str(config)]) == 0
    for path, (content, mtime) in before.items():
        assert path.read_bytes() == content and path.stat().st_mtime_ns == mtime
