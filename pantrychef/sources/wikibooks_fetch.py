"""Fetch the Wikibooks Cookbook through the official MediaWiki API.

Serial requests, a descriptive User-Agent, and ``maxlag`` follow the Wikimedia API etiquette.
The snapshot is one gzip JSON-lines file sorted by page id, so its sha256 is stable.
Each record holds the page id, title, revision id, timestamp and wikitext.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

API_URL = "https://en.wikibooks.org/w/api.php"
ROOT_CATEGORY = "Category:Recipes"
COOKBOOK_NS = 102
CATEGORY_NS = 14
BATCH = 50
MAXLAG = 5
MAX_RETRIES = 5

Transport = Callable[[dict, dict], dict]


class FetchError(RuntimeError):
    pass


@dataclass(frozen=True)
class SnapshotInfo:
    path: Path
    sha256: str
    page_count: int


def http_transport(params: dict, headers: dict) -> dict:
    url = API_URL + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310 - fixed https URL
            data = json.load(resp)
            retry = resp.headers.get("Retry-After")
    except urllib.error.HTTPError as exc:
        if exc.code in (429, 503):  # rate limit or overload: wait and retry like a lagged server
            wait = exc.headers.get("Retry-After") if exc.headers else None
            return {"error": {"code": "maxlag"}, "_retry_after": float(wait) if wait else 30.0}
        raise FetchError(f"HTTP {exc.code} from {API_URL}") from exc
    if retry:
        data["_retry_after"] = float(retry)
    return data


def _call(params: dict, ua: str, transport: Transport, sleep: Callable[[float], None]) -> dict:
    full = {"action": "query", "format": "json", "formatversion": 2, "maxlag": MAXLAG, **params}
    for _ in range(MAX_RETRIES):
        data = transport(full, {"User-Agent": ua})
        err = data.get("error")
        if not err:
            return data
        if err.get("code") != "maxlag":
            raise FetchError(f"API error: {err}")
        sleep(float(data.get("_retry_after", MAXLAG)))
    raise FetchError("server stayed lagged after retries")


def _paged(params: dict, ua: str, transport: Transport, sleep) -> list[dict]:
    """Yield every response of one query, following the ``continue`` object."""
    out, extra = [], {}
    while True:
        data = _call({**params, **extra}, ua, transport, sleep)
        out.append(data)
        if "continue" not in data:
            return out
        extra = data["continue"]


def list_pages(ua: str, transport: Transport, sleep) -> dict[int, str]:
    """Walk the recipe category tree once. Return ``{page_id: title}`` for Cookbook pages."""
    pages: dict[int, str] = {}
    seen, queue = {ROOT_CATEGORY}, [ROOT_CATEGORY]
    while queue:
        cat = queue.pop(0)
        params = {
            "list": "categorymembers",
            "cmtitle": cat,
            "cmlimit": 500,
            "cmtype": "page|subcat",
        }
        for data in _paged(params, ua, transport, sleep):
            for m in data.get("query", {}).get("categorymembers", []):
                if m["ns"] == CATEGORY_NS and m["title"] not in seen:
                    seen.add(m["title"])
                    queue.append(m["title"])
                elif m["ns"] == COOKBOOK_NS:
                    pages[m["pageid"]] = m["title"]
    return pages


def fetch_contents(titles: list[str], ua: str, transport: Transport, sleep) -> list[dict]:
    params = {
        "prop": "revisions",
        "rvprop": "ids|timestamp|content",
        "rvslots": "main",
        "titles": "|".join(titles),
    }
    merged: dict[int, dict] = {}
    for data in _paged(params, ua, transport, sleep):
        for p in data.get("query", {}).get("pages", []):
            if p.get("missing") or not p.get("revisions"):
                continue
            merged.setdefault(p["pageid"], p)
    return [_record(p) for p in merged.values()]


def _record(page: dict) -> dict:
    rev = page["revisions"][0]
    return {
        "page_id": page["pageid"],
        "title": page["title"],
        "revision_id": rev["revid"],
        "timestamp": rev["timestamp"],
        "wikitext": rev["slots"]["main"]["content"],
    }


def _write_snapshot(path: Path, records: list[dict]) -> str:
    lines = [
        json.dumps(r, sort_keys=True, ensure_ascii=False, separators=(",", ":")) for r in records
    ]
    raw = ("\n".join(lines) + "\n").encode("utf8")
    with open(path, "wb") as fh, gzip.GzipFile(fileobj=fh, mode="wb", mtime=0) as gz:
        gz.write(raw)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fetch_snapshot(
    out_dir: str | Path,
    user_agent: str,
    *,
    transport: Transport = http_transport,
    sleep: Callable[[float], None] = time.sleep,
    date: str | None = None,
    resume: bool = False,
    limit_pages: int | None = None,
) -> SnapshotInfo:
    if not user_agent.strip():
        raise ValueError("A descriptive User-Agent with a contact is required")
    out = Path(out_dir)
    cache = out / "cache"
    cache.mkdir(parents=True, exist_ok=True)
    date = date or datetime.now(UTC).strftime("%Y-%m-%d")

    pages = list_pages(user_agent, transport, sleep)
    ids = sorted(pages)[:limit_pages]
    todo = [i for i in ids if not (resume and (cache / f"{i}.json").exists())]
    for start in range(0, len(todo), BATCH):
        batch = todo[start : start + BATCH]
        for rec in fetch_contents([pages[i] for i in batch], user_agent, transport, sleep):
            (cache / f"{rec['page_id']}.json").write_text(
                json.dumps(rec, ensure_ascii=False), encoding="utf8"
            )
    records = [
        json.loads((cache / f"{i}.json").read_text(encoding="utf8"))
        for i in ids
        if (cache / f"{i}.json").exists()
    ]
    path = out / f"snapshot.{date}.jsonl.gz"
    digest = _write_snapshot(path, records)
    path.with_name(path.name + ".sha256").write_text(f"{digest}  {path.name}\n", encoding="utf8")
    return SnapshotInfo(path=path, sha256=digest, page_count=len(records))
