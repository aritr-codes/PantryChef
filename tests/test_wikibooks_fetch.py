"""Offline tests for the Wikibooks fetcher. A fake transport stands in for the MediaWiki API."""

from __future__ import annotations

import gzip
import hashlib
import json

import pytest

from pantrychef.sources.wikibooks_fetch import FetchError, fetch_snapshot

UA = "PantryChefTest/0.0 (https://example.org/contact)"


def _page(pid: int, title: str, rev: int) -> dict:
    return {
        "pageid": pid,
        "title": title,
        "revisions": [
            {
                "revid": rev,
                "timestamp": "2026-01-01T00:00:00Z",
                "slots": {"main": {"content": f"== Ingredients ==\n* {title} item"}},
            }
        ],
    }


class FakeApi:
    """Category tree: Recipes -> [Cookbook:B (pid 2), Cookbook:A (pid 1), Category:Sub].
    Sub -> [Cookbook:C (pid 3)]. Continuations are split to exercise both paths."""

    def __init__(self, maxlag_first: bool = False):
        self.calls: list[tuple[dict, dict]] = []
        self.maxlag_first = maxlag_first
        self.slept: list[float] = []

    def __call__(self, params: dict, headers: dict) -> dict:
        self.calls.append((dict(params), dict(headers)))
        if self.maxlag_first and len(self.calls) == 1:
            return {"error": {"code": "maxlag"}, "_retry_after": 7}
        if params.get("list") == "categorymembers":
            title = params["cmtitle"]
            if title == "Category:Recipes":
                if "cmcontinue" not in params:
                    return {
                        "continue": {"cmcontinue": "x", "continue": "-||"},
                        "query": {
                            "categorymembers": [
                                {"pageid": 2, "ns": 102, "title": "Cookbook:B"},
                                {"pageid": 9, "ns": 14, "title": "Category:Sub"},
                            ]
                        },
                    }
                return {
                    "query": {"categorymembers": [{"pageid": 1, "ns": 102, "title": "Cookbook:A"}]}
                }
            if title == "Category:Sub":
                return {
                    "query": {
                        "categorymembers": [
                            {"pageid": 3, "ns": 102, "title": "Cookbook:C"},
                            {"pageid": 4, "ns": 0, "title": "Not a cookbook page"},
                        ]
                    }
                }
            raise AssertionError(title)
        titles = params["titles"].split("|")
        revs = {"Cookbook:A": 11, "Cookbook:B": 22, "Cookbook:C": 33}
        pids = {"Cookbook:A": 1, "Cookbook:B": 2, "Cookbook:C": 3}
        pages = [_page(pids[t], t, revs[t]) for t in titles]
        if "rvcontinue" not in params and len(pages) > 1:
            return {
                "continue": {"rvcontinue": "y", "continue": "||"},
                "query": {"pages": pages[:1]},
            }
        if "rvcontinue" in params:
            return {"query": {"pages": pages[1:]}}
        return {"query": {"pages": pages}}


def _run(tmp_path, api, **kw):
    return fetch_snapshot(
        tmp_path,
        UA,
        transport=api,
        sleep=api.slept.append,
        date="2026-11-03",
        **kw,
    )


def _records(path):
    with gzip.open(path, "rt", encoding="utf8") as fh:
        return [json.loads(line) for line in fh]


def test_snapshot_sorted_by_page_id_with_revisions(tmp_path):
    info = _run(tmp_path, FakeApi())
    recs = _records(info.path)
    assert [r["page_id"] for r in recs] == [1, 2, 3]
    assert [r["revision_id"] for r in recs] == [11, 22, 33]
    assert recs[0]["title"] == "Cookbook:A"
    assert "wikitext" in recs[0] and recs[0]["timestamp"] == "2026-01-01T00:00:00Z"
    assert info.page_count == 3  # the ns=0 page is skipped


def test_sha256_matches_file_and_sidecar(tmp_path):
    info = _run(tmp_path, FakeApi())
    assert info.sha256 == hashlib.sha256(info.path.read_bytes()).hexdigest()
    assert info.path.with_name(info.path.name + ".sha256").read_text().split()[0] == info.sha256


def test_hash_is_stable_across_runs(tmp_path):
    a = _run(tmp_path / "a", FakeApi())
    b = _run(tmp_path / "b", FakeApi())
    assert a.sha256 == b.sha256


def test_every_request_has_user_agent_and_maxlag_and_is_serial(tmp_path):
    api = FakeApi()
    _run(tmp_path, api)
    assert api.calls
    for params, headers in api.calls:
        assert headers["User-Agent"] == UA
        assert params["maxlag"] == 5
        assert params["format"] == "json" and params["formatversion"] == 2


def test_content_request_shape(tmp_path):
    api = FakeApi()
    _run(tmp_path, api)
    content = [p for p, _ in api.calls if p.get("prop") == "revisions"]
    assert content[0]["rvslots"] == "main"
    assert "content" in content[0]["rvprop"] and "ids" in content[0]["rvprop"]
    assert len(content[0]["titles"].split("|")) <= 50


def test_maxlag_error_sleeps_retry_after_then_retries(tmp_path):
    api = FakeApi(maxlag_first=True)
    _run(tmp_path, api)
    assert 7 in api.slept


def test_persistent_maxlag_raises(tmp_path):
    def always_lag(params, headers):
        return {"error": {"code": "maxlag"}}

    with pytest.raises(FetchError):
        fetch_snapshot(tmp_path, UA, transport=always_lag, sleep=lambda s: None, date="d")


def test_resume_skips_cached_pages(tmp_path):
    first = FakeApi()
    _run(tmp_path, first)
    second = FakeApi()
    info = _run(tmp_path, second, resume=True)
    assert not [p for p, _ in second.calls if p.get("prop") == "revisions"]
    assert info.page_count == 3


def test_user_agent_required(tmp_path):
    with pytest.raises(ValueError):
        fetch_snapshot(tmp_path, "", transport=FakeApi(), date="d")
