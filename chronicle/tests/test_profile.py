"""Checks on the profile README and the animated cards' motion contract."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
README = (ROOT / "README.md").read_text(encoding="utf-8")
RAW = "https://raw.githubusercontent.com/Kush-Core/Kush-Core/main/"


def test_every_readme_image_has_alt_text():
    imgs = re.findall(r"<img\b[^>]*>", README)
    assert imgs
    for img in imgs:
        assert re.search(r'alt="[^"]+"', img), img[:80]


def test_every_static_asset_referenced_in_readme_exists():
    paths = re.findall(rf'{re.escape(RAW)}(assets/[^"]+\.svg)', README)
    assert len(paths) >= 18
    for rel in paths:
        assert (ROOT / rel).exists(), rel


def test_project_cards_link_to_their_repositories():
    cards = re.findall(r'<a href="https://github\.com/Kush-Core/([^"]+)"><picture>.*?assets/deed-([a-z0-9_-]+)-dark\.svg', README)
    assert [(repo.lower(), slug) for repo, slug in cards] == [
        ("narrative_mind", "narrative_mind"), ("hubahu", "hubahu"),
        ("renewal-risk", "renewal-risk"), ("throttling1", "throttling1")]


def test_text_versions_are_collapsed_but_present():
    assert README.count("<details><summary>Text version</summary>") == 2
    assert "| Deed | What it does | Stack |" in README
    assert "- B.Tech CSE, MIT Bengaluru ('27)" in README


def _css(name):
    svg = (ROOT / "assets" / name).read_text(encoding="utf-8")
    return re.search(r"<style>(.*?)</style>", svg, re.S).group(1)


def test_motion_contract_resting_states_are_visible():
    for name in ("proclamation-dark.svg", "proclamation-light.svg", "deed-hubahu-dark.svg", "deed-throttling1-light.svg"):
        css = _css(name)
        assert "@media (prefers-reduced-motion: reduce) { * { animation: none !important; } }" in css
        assert re.search(r"\.draw \{ stroke-dasharray: 1; stroke-dashoffset: 0;", css)
        assert re.search(r"\.rise \{ opacity: 1;", css)
        assert re.search(r"\.type \{[^}]*transform: scaleX\(0\);", css)  # typing cover hidden at rest
        assert re.search(r"\.pulse \{ opacity: 0;", css)                 # pulse invisible at rest
        loops = [float(s) for s in re.findall(r"animation: \w+ ([0-9.]+)s [^;]*infinite", css)]
        assert loops and min(loops) >= 7, loops                          # slow loops only


def test_existing_flicker_and_cursor_rules_unchanged():
    css = _css("frontispiece-dark.svg")
    assert ".name { animation: flicker 6s infinite; }" in css
    assert "92%,94%{opacity:.55}" in css


def test_armory_blinks_slowly_and_text_stays_still():
    for name in ("armory-dark.svg", "armory-light.svg"):
        svg = (ROOT / "assets" / name).read_text(encoding="utf-8")
        css = _css(name)
        assert "@media (prefers-reduced-motion: reduce) { * { animation: none !important; } }" in css
        assert re.search(r"\.led \{ opacity: 1;", css)          # LEDs fully visible at rest
        assert re.search(r"\.glow \{ opacity: 0\.\d+;", css)    # glow visible at rest
        periods = [float(s) for s in re.findall(r"animation: \w+ ([0-9.]+)s [^;]*infinite", css)]
        assert periods and min(periods) >= 3, periods           # slow: well under 3 flashes per second
        assert svg.count('class="led"') == 10 and svg.count('class="glow"') == 5
        # Only the LED groups and glow outlines are animated; text paths carry no class.
        assert set(re.findall(r'class="([^"]+)"', svg)) == {"led", "glow"}
