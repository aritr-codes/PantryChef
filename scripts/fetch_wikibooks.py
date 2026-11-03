"""Fetch a Wikibooks Cookbook snapshot with the official MediaWiki API.

Example:
    uv run python scripts/fetch_wikibooks.py --out data/raw/wikibooks --limit 20
"""

from __future__ import annotations

import argparse

from pantrychef.sources.wikibooks_fetch import fetch_snapshot

DEFAULT_UA = "PantryChef/0.4 (https://github.com/aritr-codes/PantryChef; recipe research)"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="data/raw/wikibooks")
    ap.add_argument("--user-agent", default=DEFAULT_UA)
    ap.add_argument("--limit", type=int, default=None, help="Fetch only the first N pages by id.")
    ap.add_argument("--resume", action="store_true", help="Reuse pages cached by an earlier run.")
    args = ap.parse_args()
    info = fetch_snapshot(args.out, args.user_agent, limit_pages=args.limit, resume=args.resume)
    print(f"{info.page_count} pages -> {info.path}\nsha256 {info.sha256}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
