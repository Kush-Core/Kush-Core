"""Fetch a user's recent public GitHub events and keep the ones the Chronicle shows.

Endpoint: GET /users/{user}/events/public?per_page=100. GitHub returns at most
300 events, all from the past 90 days, and an event can take from 30 s to 6 h
to appear. Kept: pushes, pull requests opened or merged, published releases,
and newly created repositories. Payload fields are read defensively: when a
push payload lacks a commit count or message, the compare API fills them in.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime

API = "https://api.github.com"
LIMIT = 5

Getter = Callable[[str, "str | None"], object]


class FetchError(Exception):
    """An API call failed. ``status`` is the HTTP status, or None for network errors."""

    def __init__(self, status: int | None, message: str):
        super().__init__(f"HTTP {status}: {message}" if status else message)
        self.status = status

    @property
    def keep_previous(self) -> bool:
        """403 (including rate limits), 429, 5xx and network failures are treated as
        temporary: the previous dist/ files are kept and the run exits 0."""
        return self.status is None or self.status in (403, 429) or 500 <= self.status <= 599


def _get(url: str, token: str | None, timeout: float = 20) -> object:
    request = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": "kush-core-chronicle",
    })
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:  # subclass of URLError: catch first
        raise FetchError(exc.code, str(exc.reason)) from None
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        raise FetchError(None, f"{type(exc).__name__}: {exc}") from None


@dataclass(frozen=True)
class Entry:
    when: datetime          # event time, timezone-aware (UTC from the API)
    repo: str               # owner/name
    kind: str               # push | pr_opened | pr_merged | release | founded
    count: int | None       # commits in a push; None if unknown
    message: str            # untrusted text: commit message, PR title, release name


def fetch_events(user: str, token: str | None, get: Getter | None = None) -> list[dict]:
    get = get or _get
    url = f"{API}/users/{urllib.parse.quote(user, safe='')}/events/public?per_page=100"
    data = get(url, token)
    if not isinstance(data, list):
        raise FetchError(None, "unexpected response shape (expected a list of events)")
    return [e for e in data if isinstance(e, dict)]


def _classify(event: dict) -> Entry | None:
    kind_name = event.get("type")
    payload = event.get("payload") or {}
    repo = (event.get("repo") or {}).get("name") or "?"
    try:
        when = datetime.fromisoformat(str(event.get("created_at")).replace("Z", "+00:00"))
    except ValueError:
        return None

    if kind_name == "PushEvent":
        commits = payload.get("commits") or []
        count = payload.get("size")
        if not isinstance(count, int):
            count = len(commits) if commits else None
        message = (commits[-1].get("message") if commits and isinstance(commits[-1], dict) else "") or ""
        return Entry(when, repo, "push", count, message)

    if kind_name == "PullRequestEvent":
        # Observed 2026-11-02: payloads are trimmed (pull_request carries only
        # base/head/id/number/url, no title) and a merge arrives as action
        # "merged". The older form, "closed" with merged=true, is also accepted.
        pr = payload.get("pull_request") or {}
        title = pr.get("title") or ""
        action = payload.get("action")
        if action == "opened":
            return Entry(when, repo, "pr_opened", None, title)
        if action == "merged" or (action == "closed" and (pr.get("merged") is True or pr.get("merged_at"))):
            return Entry(when, repo, "pr_merged", None, title)
        return None

    if kind_name == "ReleaseEvent" and payload.get("action") == "published":
        release = payload.get("release") or {}
        return Entry(when, repo, "release", None, release.get("name") or release.get("tag_name") or "")

    if kind_name == "CreateEvent" and payload.get("ref_type") == "repository":
        return Entry(when, repo, "founded", None, payload.get("description") or "")

    return None


def _complete_push(entry: Entry, event: dict, token: str | None, get: Getter) -> Entry:
    """Fill a push's commit count and/or message from the compare API if missing."""
    if entry.count is not None and entry.message:
        return entry
    payload = event.get("payload") or {}
    before, head = payload.get("before"), payload.get("head")
    if not (before and head):
        return entry
    url = f"{API}/repos/{entry.repo}/compare/{before}...{head}"
    try:
        data = get(url, token)
    except FetchError:
        return entry
    if not isinstance(data, dict):
        return entry
    count = entry.count if entry.count is not None else data.get("total_commits")
    commits = data.get("commits") or []
    message = entry.message or ((commits[-1].get("commit") or {}).get("message") if commits else "") or ""
    return Entry(entry.when, entry.repo, entry.kind, count if isinstance(count, int) else None, message)


def _complete_pr(entry: Entry, event: dict, token: str | None, get: Getter) -> Entry:
    """Trimmed PR payloads carry no title: read it from the pull request itself.
    Only api.github.com URLs are followed, because the request carries the token.
    If the lookup fails, the PR number ("#12") is shown instead."""
    if entry.message:
        return entry
    payload = event.get("payload") or {}
    pr = payload.get("pull_request") or {}
    number = pr.get("number") or payload.get("number")
    fallback = f"#{number}" if number else ""
    url = pr.get("url")
    if not (isinstance(url, str) and url.startswith(API + "/")):
        url = f"{API}/repos/{entry.repo}/pulls/{number}" if number else None
    if not url:
        return replace(entry, message=fallback)
    try:
        data = get(url, token)
    except FetchError:
        data = None
    title = data.get("title") if isinstance(data, dict) else None
    return replace(entry, message=title if isinstance(title, str) and title else fallback)


def _complete(entry: Entry, event: dict, token: str | None, get: Getter) -> Entry:
    if entry.kind == "push":
        return _complete_push(entry, event, token, get)
    if entry.kind in ("pr_opened", "pr_merged"):
        return _complete_pr(entry, event, token, get)
    return entry


def select(events: list[dict], token: str | None = None, get: Getter | None = None, limit: int = LIMIT) -> list[Entry]:
    """Newest ``limit`` kept events, newest first, with missing details filled in."""
    get = get or _get
    kept = [(entry, event) for event in events if (entry := _classify(event))]
    kept.sort(key=lambda pair: pair[0].when, reverse=True)
    return [_complete(e, ev, token, get) for e, ev in kept[:limit]]
