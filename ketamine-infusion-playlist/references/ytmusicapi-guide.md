# ytmusicapi reference (as used by this skill)

Docs: https://ytmusicapi.readthedocs.io/ · Repo: https://github.com/sigma67/ytmusicapi

## Install

Homebrew Python (3.11 on this machine) enforces PEP 668 (externally-managed environment), so
install into a dedicated venv rather than system Python:

```bash
python3 -m venv ~/.local/share/ketamine-playlist/venv
~/.local/share/ketamine-playlist/venv/bin/pip install -r requirements.txt
```

Run every script through that venv's python, e.g.:

```bash
~/.local/share/ketamine-playlist/venv/bin/python3 scripts/build_playlist.py --dry-run --plan plan.json
```

## Auth (browser-headers method)

`ytmusicapi.setup(filepath=...)` (wrapped by `scripts/setup_auth.py`) prompts the user to
paste request headers copied from music.youtube.com in the browser and writes them to a JSON
file. Steps (also printed by `setup_auth.py`):

1. Open music.youtube.com, logged in.
2. DevTools -> Network tab -> filter for `/browse` requests.
3. Click a POST request with status 200.
4. Copy the request headers (Firefox: right-click -> Copy -> Copy Request Headers; Chrome/Edge:
   "Copy as fetch (Node.js)" and extract Accept, Authorization, Content-Type, X-Goog-AuthUser,
   x-origin, Cookie).
5. Paste when prompted.

The resulting file (`~/.local/share/ketamine-playlist/browser.json`) contains session cookies
— never commit it. It can go stale (session expiry); `setup_auth.py` verifies it with a live
search call and offers `--force` to redo the capture.

```python
from ytmusicapi import YTMusic
yt = YTMusic("~/.local/share/ketamine-playlist/browser.json")
```

## Calls this skill uses

- `search(query, filter="songs", limit=5)` -> list of dicts with `videoId`, `title`,
  `artists` (list of `{name, id}`), `album`, `duration` (str), `duration_seconds` (int).
  Falls back to `filter="videos"` if a song search comes up empty (some tracks are only
  catalogued as videos).
- `create_playlist(title, description, privacy_status="UNLISTED", video_ids=None)` -> returns
  the new `playlistId`. `privacy_status` is one of `PUBLIC` / `PRIVATE` / `UNLISTED`.
- `add_playlist_items(playlistId, videoIds, duplicates=True)` -> adds items in the given list
  order, so phase ordering (Build -> Peak -> Wind-down) is preserved in the playlist.
- `get_playlist(playlistId, limit=None)` -> dict including a `tracks` list (each with
  `videoId`); used to fetch the live contents of excluded playlists.
- `get_library_playlists(limit=None)` -> list of `{playlistId, title, count, ...}`; used to
  let the user pick which existing playlists to exclude from, on first run.

## Notes

- Track resolution is fuzzy — always sanity-check the top search result's title/artist against
  the intended query before treating it as a match (the skill's `resolve_track()` helper in
  `scripts/ytm.py` takes the first result only; if that's ever wrong for a given query, prefer a
  more specific query string over trusting a bad match).
- `duration_seconds` is the source of truth for timeline math, not the human-readable `duration`.
