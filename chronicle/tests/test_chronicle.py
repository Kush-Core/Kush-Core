import re
import xml.etree.ElementTree as ET
from datetime import date
from pathlib import Path

import pytest

from chronicle import fetch, render
from chronicle.roman import roman_date, to_roman

ROOT = Path(__file__).resolve().parents[2]
MAX_SVG_BYTES = 100_000


def ev(kind, created, repo="Kush-Core/demo", **payload):
    return {"type": kind, "created_at": created, "repo": {"name": repo}, "payload": payload}


EVENTS = [
    ev("PushEvent", "2026-11-02T08:00:00Z", size=3,
       commits=[{"message": "first"}, {"message": "<script>&</script> second\nbody line"}]),
    ev("PullRequestEvent", "2026-11-01T08:00:00Z", action="opened", pull_request={"title": "Add tests"}),
    ev("PullRequestEvent", "2026-10-31T08:00:00Z", action="closed", pull_request={"title": "Merge me", "merged": True}),
    ev("PullRequestEvent", "2026-10-30T08:00:00Z", action="closed", pull_request={"title": "Unmerged", "merged": False}),
    ev("ReleaseEvent", "2026-10-29T08:00:00Z", action="published", release={"name": "v1.0", "tag_name": "v1.0"}),
    ev("CreateEvent", "2026-10-28T08:00:00Z", repo="Kush-Core/newrepo", ref_type="repository", description="New"),
    ev("CreateEvent", "2026-10-27T08:00:00Z", ref_type="branch"),
    ev("WatchEvent", "2026-10-26T08:00:00Z", action="started"),
    ev("PushEvent", "2026-10-25T08:00:00Z", size=1, commits=[{"message": "older push, beyond the limit"}]),
]


def no_network(url, token):
    raise AssertionError(f"unexpected API call: {url}")


# ------------------------------------------------------------------ roman
@pytest.mark.parametrize("n, expected", [
    (1, "I"), (4, "IV"), (9, "IX"), (14, "XIV"), (40, "XL"), (90, "XC"),
    (400, "CD"), (1994, "MCMXCIV"), (2026, "MMXXVI"),
])
def test_roman(n, expected):
    assert to_roman(n) == expected


def test_roman_date():
    assert roman_date(date(2026, 11, 2)) == "II·XI·MMXXVI"


@pytest.mark.parametrize("bad", [0, 4000, -1, True, 2.0])
def test_roman_rejects_out_of_range(bad):
    with pytest.raises(ValueError):
        to_roman(bad)


# ------------------------------------------------------------------ selection
def test_select_keeps_five_newest_relevant_events():
    entries = fetch.select(EVENTS, get=no_network)
    assert [e.kind for e in entries] == ["push", "pr_opened", "pr_merged", "release", "founded"]
    assert entries[0].count == 3


def test_push_without_count_or_message_uses_compare():
    event = ev("PushEvent", "2026-11-02T08:00:00Z", before="a" * 40, head="b" * 40)
    calls = []

    def get(url, token):
        calls.append(url)
        return {"total_commits": 4, "commits": [{"commit": {"message": "via compare"}}]}

    (entry,) = fetch.select([event], get=get)
    assert (entry.count, entry.message) == (4, "via compare")
    assert calls == [f"https://api.github.com/repos/Kush-Core/demo/compare/{'a' * 40}...{'b' * 40}"]
    assert render.label(entry) == "forged 4 commits"


def test_push_compare_failure_degrades_gracefully():
    event = ev("PushEvent", "2026-11-02T08:00:00Z", before="a" * 40, head="b" * 40)

    def get(url, token):
        raise fetch.FetchError(500, "boom")

    (entry,) = fetch.select([event], get=get)
    assert entry.count is None and render.label(entry) == "forged commits"


def test_labels_in_output():
    svg = render.render(fetch.select(EVENTS, get=no_network), "Kush-Core", "dark")
    for text in ("forged 3 commits", "petitioned", "sealed", "proclaimed", "founded", "II·XI·MMXXVI"):
        assert text in svg
    assert "Unmerged" not in svg and "older push" not in svg


# ------------------------------------------------------------------ escaping and cleaning
def test_script_input_is_escaped():
    svg = render.render(fetch.select(EVENTS, get=no_network), "Kush-Core", "dark")
    assert "<script" not in svg
    assert "&lt;script&gt;&amp;" in svg
    ET.fromstring(svg)


def test_clean_replaces_and_truncates():
    assert render.clean("héllo ✓ ok", 60) == "h?llo ? ok"
    assert render.clean("first\nsecond", 60) == "first"
    assert render.clean(None, 60) == ""
    long = render.clean("x" * 80, 60)
    assert len(long) == 60 and long.endswith("...")
    assert render.clean("y" * 60, 60) == "y" * 60
    assert render.clean("· → ▸", 60) == "· → ▸"


# ------------------------------------------------------------------ empty state
def test_empty_events_fallback(tmp_path):
    for path in render.write([], "Kush-Core", tmp_path):
        assert "The scribe rests." in path.read_text(encoding="utf-8")


# ------------------------------------------------------------------ SVG properties
@pytest.fixture
def svgs(tmp_path):
    rendered = render.write(fetch.select(EVENTS, get=no_network), "Kush-Core", tmp_path / "events")
    empty = render.write([], "Kush-Core", tmp_path / "empty")
    statics = sorted((ROOT / "assets").glob("*.svg"))
    assert len(statics) == 18, "expected the 18 static assets in assets/"
    return rendered + empty + statics


def test_every_svg_parses(svgs):
    for path in svgs:
        ET.parse(path)


def test_no_external_urls_except_xmlns(svgs):
    for path in svgs:
        text = re.sub(r'\sxmlns(?::\w+)?="[^"]*"', "", path.read_text(encoding="utf-8"))
        assert not re.search(r"https?://", text), path.name


def test_svg_size_limit(svgs):
    for path in svgs:
        assert path.stat().st_size <= MAX_SVG_BYTES, f"{path.name}: {path.stat().st_size} bytes"


def test_motion_rules():
    svg = render.render([], "Kush-Core", "light")
    period = float(re.search(r"animation: blink ([0-9.]+)s", svg).group(1))
    assert period >= 1.2
    assert "@media (prefers-reduced-motion: reduce)" in svg
    assert "data:font/woff2;base64," in svg


# ------------------------------------------------------------------ failure paths
@pytest.mark.parametrize("status", [403, 429, 500, 503, None])
def test_temporary_api_failure_leaves_existing_files_untouched(tmp_path, monkeypatch, status):
    before = {}
    for theme in ("dark", "light"):
        path = tmp_path / f"chronicle-{theme}.svg"
        path.write_text(f"previous {theme}", encoding="utf-8")
        before[path] = (path.read_bytes(), path.stat().st_mtime_ns)

    def failing_get(url, token):
        raise fetch.FetchError(status, "simulated")

    monkeypatch.setattr(fetch, "_get", failing_get)
    assert render.main(["--user", "Kush-Core", "--out", str(tmp_path)]) == 0
    for path, (content, mtime) in before.items():
        assert path.read_bytes() == content and path.stat().st_mtime_ns == mtime
    assert sorted(p.name for p in tmp_path.iterdir()) == ["chronicle-dark.svg", "chronicle-light.svg"]


def test_non_temporary_api_failure_is_raised(tmp_path, monkeypatch):
    def failing_get(url, token):
        raise fetch.FetchError(401, "bad credentials")

    monkeypatch.setattr(fetch, "_get", failing_get)
    with pytest.raises(fetch.FetchError):
        render.main(["--user", "Kush-Core", "--out", str(tmp_path)])


# ------------------------------------------------------------------ workflow / tokens consistency
def test_workflow_snake_colours_match_tokens():
    import json

    tokens = json.loads((ROOT / "tokens.json").read_text(encoding="utf-8"))["tapestry"]
    workflow = (ROOT / ".github" / "workflows" / "illuminate.yml").read_text(encoding="utf-8")
    for theme, spec in tokens.items():
        if theme.startswith("$"):
            continue
        assert len(spec["dots"]) == 5
        expected = f"dist/tapestry-{theme}.svg?color_snake={spec['snake']}&color_dots={','.join(spec['dots'])}"
        assert expected in workflow, f"workflow colours for {theme} differ from tokens.json"


# ------------------------------------------------------------------ trimmed PR payloads (observed 2026-11-02)
def trimmed_pr(action, number, created, url=None):
    return ev("PullRequestEvent", created, action=action, number=number, pull_request={
        "base": {}, "head": {}, "id": 1000 + number, "number": number,
        "url": url or f"https://api.github.com/repos/Kush-Core/demo/pulls/{number}",
    })


def test_trimmed_pr_payloads_are_recognised_and_titled():
    events = [trimmed_pr("merged", 7, "2026-11-02T19:57:15Z"), trimmed_pr("opened", 7, "2026-11-02T19:53:30Z")]
    calls = []

    def get(url, token):
        calls.append(url)
        return {"title": "Real title"}

    merged, opened = fetch.select(events, get=get)
    assert (merged.kind, opened.kind) == ("pr_merged", "pr_opened")
    assert merged.message == opened.message == "Real title"
    assert (render.label(merged), render.label(opened)) == ("sealed", "petitioned")
    assert calls == ["https://api.github.com/repos/Kush-Core/demo/pulls/7"] * 2


def test_pr_title_lookup_failure_falls_back_to_number():
    def get(url, token):
        raise fetch.FetchError(404, "gone")

    (entry,) = fetch.select([trimmed_pr("opened", 9, "2026-11-02T10:00:00Z")], get=get)
    assert entry.message == "#9"


def test_pr_url_off_api_host_is_not_followed():
    calls = []

    def get(url, token):
        calls.append(url)
        return {"title": "t"}

    fetch.select([trimmed_pr("opened", 5, "2026-11-02T10:00:00Z", url="https://evil.example/steal")], get=get)
    assert calls == ["https://api.github.com/repos/Kush-Core/demo/pulls/5"]
