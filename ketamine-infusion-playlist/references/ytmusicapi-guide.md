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

- `search(query, filter="songs", limit=N)` -> list of dicts with `videoId`, `title`,
  `artists` (list of `{name, id}`), `album`, `duration` (str), `duration_seconds` (int).
  Falls back to `filter="videos"` if a song search comes up empty (some tracks are only
  catalogued as videos).
- `create_playlist(title, description, privacy_status="UNLISTED", video_ids=None)` -> returns
  the new `playlistId`. `privacy_status` is one of `PUBLIC` / `PRIVATE` / `UNLISTED`.
- `add_playlist_items(playlistId, videoIds, duplicates=True)` -> adds items in the given list
  order, so phase ordering (Build -> Peak -> Wind-down) is preserved in the playlist. **Can
  transiently return HTTP 409 Conflict immediately after `create_playlist`** — confirmed by
  live testing, not documented behavior. `build_playlist.py`'s `_add_items_with_retry` retries
  up to 3 times with backoff; call through it rather than the raw API when adding items right
  after creating a playlist.
- `remove_playlist_items(playlistId, videos)` -> each item needs **both** `videoId` and
  `setVideoId`. `setVideoId` is only available from `get_playlist()` (search results don't have
  it) — fetch the live playlist first if you need to remove specific items.
- **No reorder primitive.** There is no API call to move an item to a specific position.
  `--sync`'s approach (remove everything, then re-add in the desired order) is the reliable way
  to get an exact track order, at the cost of transiently emptying the playlist mid-operation.
- `get_playlist(playlistId, limit=None)` -> dict including a `tracks` list (each with
  `videoId`, `setVideoId`, `title`, `artists`, `duration_seconds`); used both to fetch the live
  contents of excluded playlists and, via `--show`/`--sync`, to edit a live playlist.
- `get_library_playlists(limit=None)` -> list of `{playlistId, title, count, ...}`; used to
  let the user pick which existing playlists to exclude from, on first run.
- `delete_playlist(playlistId)` -> permanently deletes a playlist. Not used by any script
  command (no destructive playlist-deletion feature exists here); only ever called ad hoc to
  clean up a throwaway test playlist during development.

## Vocal/lyrics detection (instrumental-only rule)

- `get_watch_playlist(videoId=...)` returns a dict that may include a `"lyrics"` key holding a
  browseId; `get_lyrics(browseId)` resolves that to `{"lyrics": "...", ...}` if lyrics text
  exists.
- **This is not fully reliable, confirmed by live testing:** the `lyrics` browseId can be
  present on purely instrumental tracks (false positive on presence alone), and `get_lyrics`
  has returned `None` even for a track with confirmed audible vocals (false negative). Do not
  treat browseId presence, or `get_lyrics` success alone, as a reliable signal either way.
- `ytm.check_vocals(client, video_id)` treats **actual returned lyrics text** as the only
  positive signal (`True`); a missing browseId or empty lyrics is `False`; a lookup exception is
  `None` (inconclusive, never blocking). Results are cached to `lyrics-cache.json` (only
  definitive `True`/`False`, never `None`, so a failed lookup is retried next run).
- Because the lyrics signal alone has false negatives, `build_playlist.py` ORs it with
  `ytm.is_likely_vocal_title()` (title contains `feat.`/`ft.`/`featuring`, or the track only
  resolved via the `"videos"` search filter rather than `"songs"`) as an advisory-level flag.
  Per explicit user instruction: confirmed lyrics is always a hard block; the title heuristic
  is a flag to review, not an auto-block; a plan's `vocal_ok` list can manually clear a verified
  false positive.

## Notes

- Track resolution is fuzzy — always sanity-check a search result's title/artist against the
  intended query before treating it as a match. `ytm.resolve_track()` takes only the top result;
  when a query might be ambiguous (edits/remixes/features sharing a title with the plain track —
  this has happened in practice, e.g. "Max Cooper - Repetition" top-matching "Repetition
  (Edit)"), use `scripts/search_tracks.py -n 5 "Artist - Title"` (backed by
  `ytm.resolve_candidates()`) to see multiple candidates and pick deliberately, or narrow the
  query string.
- `duration_seconds` is the source of truth for timeline math, not the human-readable `duration`.
