#!/usr/bin/env python3
"""Resolve free-text track queries to concrete YouTube Music tracks.

Standalone utility used during curation to test candidate tracks before
committing them to a playlist plan (see build_playlist.py). Takes one or
more "Artist - Title" queries and prints resolved matches (videoId,
duration, matched artist) as JSON.

By default prints one top-match object per query, in input order (`null`
for unresolved queries) -- unchanged from the original flat shape. Pass
-n/--limit > 1 to audition multiple candidates per query instead (useful
for disambiguating versions/edits/covers before committing a query to a
plan); output becomes one {"query", "candidates": [...]} object per query.

Usage:
    python3 search_tracks.py "Max Cooper - Repeat" "Stars of the Lid - Requiem for Dying Mothers"
    python3 search_tracks.py -n 5 "Max Cooper - Repeat"
"""
from __future__ import annotations

import argparse
import json
import sys

from ytm import get_client, resolve_candidates, resolve_track


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("queries", nargs="+", metavar="QUERY", help='e.g. "Artist - Title"')
    parser.add_argument("-n", "--limit", type=int, default=1, help="candidates to show per query (default 1)")
    args = parser.parse_args()

    client = get_client()

    if args.limit == 1:
        results = [resolve_track(client, q) for q in args.queries]
        print(json.dumps(results, indent=2, ensure_ascii=False))
        misses = [q for r, q in zip(results, args.queries) if r is None]
    else:
        results = [{"query": q, "candidates": resolve_candidates(client, q, limit=args.limit)} for q in args.queries]
        print(json.dumps(results, indent=2, ensure_ascii=False))
        misses = [r["query"] for r in results if not r["candidates"]]

    if misses:
        print(f"\n{len(misses)} unresolved: {misses}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
