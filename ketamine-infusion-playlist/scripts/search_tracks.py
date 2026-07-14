#!/usr/bin/env python3
"""Resolve free-text track queries to concrete YouTube Music tracks.

Standalone utility used during curation to test candidate tracks before
committing them to a playlist plan (see build_playlist.py). Takes one or
more "Artist - Title" queries and prints resolved matches (videoId,
duration, matched artist) as JSON, one object per query, in input order.
Unresolved queries print as `null`.

Usage:
    python3 search_tracks.py "Max Cooper - Repeat" "Stars of the Lid - Requiem for Dying Mothers"
"""
from __future__ import annotations

import json
import sys

from ytm import get_client, resolve_track


def main() -> int:
    queries = sys.argv[1:]
    if not queries:
        print(__doc__)
        return 1

    client = get_client()
    results = [resolve_track(client, q) for q in queries]
    print(json.dumps(results, indent=2, ensure_ascii=False))

    misses = [r["query"] if r else q for r, q in zip(results, queries) if r is None]
    if misses:
        print(f"\n{len(misses)} unresolved: {misses}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
