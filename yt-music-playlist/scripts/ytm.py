"""Shared helpers for the yt-music-playlist skill.

Holds the shared runtime-state paths (auth file, lyrics cache), and small
wrappers around ytmusicapi used by the other scripts. Nothing in here is a
CLI entrypoint on its own.

Auth and the lyrics cache are account-level, not specific to any one
playlist protocol, so they live in a shared state dir used by every
consumer of this skill. Exclude lists (which playlists/tracks not to
reuse) are protocol-specific, so callers pass in their own `exclude_dir`
rather than this module hard-coding one.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

STATE_DIR = Path.home() / ".local" / "share" / "yt-music-playlist"
AUTH_FILE = STATE_DIR / "browser.json"
LYRICS_CACHE_FILE = STATE_DIR / "lyrics-cache.json"


def ensure_state_dir() -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)


def get_client():
    """Return an authenticated YTMusic client, or raise a clear error."""
    from ytmusicapi import YTMusic

    if not AUTH_FILE.exists():
        raise FileNotFoundError(
            f"No auth file at {AUTH_FILE}. Run scripts/setup_auth.py first."
        )
    return YTMusic(str(AUTH_FILE))


# --- Exclude lists (per-consumer, directory passed in by caller) ---
# Two sibling files per exclude_dir: exclude-playlists.json (whole playlists
# whose tracks should never be reused) and exclude-tracks.json (individual
# tracks permanently banned regardless of playlist), deliberately keyed by
# "id" vs "videoId" so the two files' schemas stay visually distinguishable.

def _exclude_playlists_file(exclude_dir: Path | str) -> Path:
    return Path(exclude_dir) / "exclude-playlists.json"


def _exclude_tracks_file(exclude_dir: Path | str) -> Path:
    return Path(exclude_dir) / "exclude-tracks.json"


def load_exclude_list(exclude_dir: Path | str) -> list[dict[str, str]]:
    f = _exclude_playlists_file(exclude_dir)
    if not f.exists():
        return []
    return json.loads(f.read_text())


def save_exclude_list(exclude_dir: Path | str, entries: list[dict[str, str]]) -> None:
    Path(exclude_dir).mkdir(parents=True, exist_ok=True)
    _exclude_playlists_file(exclude_dir).write_text(json.dumps(entries, indent=2, ensure_ascii=False) + "\n")


def add_to_exclude_list(exclude_dir: Path | str, playlist_id: str, name: str) -> list[dict[str, str]]:
    entries = load_exclude_list(exclude_dir)
    if not any(e["id"] == playlist_id for e in entries):
        entries.append({"id": playlist_id, "name": name})
        save_exclude_list(exclude_dir, entries)
    return entries


def remove_from_exclude_list(exclude_dir: Path | str, playlist_ids: list[str]) -> list[dict[str, str]]:
    ids = set(playlist_ids)
    entries = [e for e in load_exclude_list(exclude_dir) if e["id"] not in ids]
    save_exclude_list(exclude_dir, entries)
    return entries


def get_excluded_video_ids(client, exclude_dir: Path | str) -> set[str]:
    """Union the videoIds of every playlist in the exclude-list, fetched live."""
    excluded: set[str] = set()
    for entry in load_exclude_list(exclude_dir):
        try:
            playlist = client.get_playlist(entry["id"], limit=None)
        except Exception as exc:  # noqa: BLE001 - surface but don't abort the run
            print(f"  warning: could not fetch excluded playlist {entry['id']!r} "
                  f"({entry.get('name', '?')}): {exc}")
            continue
        for track in playlist.get("tracks", []):
            vid = track.get("videoId")
            if vid:
                excluded.add(vid)
    return excluded


# --- Permanent per-track exclusion list (tracks banned regardless of playlist) ---

def load_exclude_tracks(exclude_dir: Path | str) -> list[dict[str, str]]:
    f = _exclude_tracks_file(exclude_dir)
    if not f.exists():
        return []
    return json.loads(f.read_text())


def save_exclude_tracks(exclude_dir: Path | str, entries: list[dict[str, str]]) -> None:
    Path(exclude_dir).mkdir(parents=True, exist_ok=True)
    _exclude_tracks_file(exclude_dir).write_text(json.dumps(entries, indent=2, ensure_ascii=False) + "\n")


def add_to_exclude_tracks(exclude_dir: Path | str, video_id: str, name: str) -> list[dict[str, str]]:
    entries = load_exclude_tracks(exclude_dir)
    if not any(e["videoId"] == video_id for e in entries):
        entries.append({"videoId": video_id, "name": name})
        save_exclude_tracks(exclude_dir, entries)
    return entries


def get_excluded_track_video_ids(exclude_dir: Path | str) -> set[str]:
    """videoIds from the permanent per-track exclude file. No network needed."""
    return {e["videoId"] for e in load_exclude_tracks(exclude_dir) if e.get("videoId")}


def get_all_excluded_video_ids(client, exclude_dir: Path | str) -> set[str]:
    """Union of (a) tracks in every excluded playlist and (b) the permanent
    per-track exclude list. This is what playlist-building should check
    against; get_excluded_video_ids() stays playlist-only for callers (like
    --sync) that need to subtract out a specific playlist's own tracks."""
    return get_excluded_video_ids(client, exclude_dir) | get_excluded_track_video_ids(exclude_dir)


# --- Instrumental/vocal detection (optional, policy-gated by the caller) ---
# Detection combines a hard lyrics-text signal (check_vocals) with a soft
# title heuristic (is_likely_vocal_title). Whether/how these are enforced
# (block vs flag vs off, and any exception for a closing vocal track) is a
# protocol policy decision made by build_playlist.py, not by this module.
VOCAL_TITLE_MARKERS = ("feat.", "ft.", "featuring", "(feat", "(ft")


def load_lyrics_cache() -> dict[str, bool]:
    if not LYRICS_CACHE_FILE.exists():
        return {}
    return json.loads(LYRICS_CACHE_FILE.read_text())


def save_lyrics_cache(cache: dict[str, bool]) -> None:
    ensure_state_dir()
    LYRICS_CACHE_FILE.write_text(json.dumps(cache, indent=2, ensure_ascii=False) + "\n")


def check_vocals(client, video_id: str) -> bool | None:
    """True = confirmed lyrics text found, False = confirmed none available,
    None = lookup failed/inconclusive. Only True/False are cached -- a failed
    lookup is retried on the next run rather than silently treated as safe."""
    cache = load_lyrics_cache()
    if video_id in cache:
        return cache[video_id]
    try:
        watch = client.get_watch_playlist(videoId=video_id)
        browse_id = (watch or {}).get("lyrics")
        if not browse_id:
            result = False
        else:
            lyrics = client.get_lyrics(browse_id)
            text = (lyrics or {}).get("lyrics")
            result = bool(text and text.strip())
    except Exception:  # noqa: BLE001 - inconclusive, not a confirmed non-match
        return None
    cache[video_id] = result
    save_lyrics_cache(cache)
    return result


def is_likely_vocal_title(track: dict[str, Any]) -> bool:
    """Cheap title-based heuristic, OR'd alongside check_vocals()."""
    title = (track.get("title") or "").lower()
    if any(marker in title for marker in VOCAL_TITLE_MARKERS):
        return True
    # Tracks only catalogued as a "video" (not a "song") skew more often
    # toward non-instrumental content on YouTube Music -- weak signal.
    return track.get("matched_filter") == "videos"


def resolve_candidates(client, query: str, limit: int = 5) -> list[dict[str, Any]]:
    """Resolve a free-text 'Artist - Title' query to up to `limit` candidate
    tracks, for disambiguating between versions/edits/covers before
    committing a query to a plan (search results are fuzzy and the top hit
    isn't always the intended one -- see search_tracks.py -n).

    Tries the "songs" filter first, falls back to "videos" only if that comes
    up completely empty (some tracks are only catalogued as videos on
    YouTube Music). De-duplicates by videoId.
    """
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    for filt in ("songs", "videos"):
        try:
            results = client.search(query, filter=filt, limit=limit)
        except Exception:  # noqa: BLE001
            results = []
        for r in results:
            vid = r.get("videoId")
            if not vid or vid in seen:
                continue
            seen.add(vid)
            artists = r.get("artists") or []
            candidates.append({
                "query": query,
                "videoId": vid,
                "title": r.get("title"),
                "artist": artists[0]["name"] if artists else "Unknown",
                "duration_seconds": r.get("duration_seconds"),
                "matched_filter": filt,
            })
        if candidates:
            break
    return candidates[:limit]


def resolve_track(client, query: str) -> dict[str, Any] | None:
    """Resolve a free-text 'Artist - Title' query to its single best-match track."""
    candidates = resolve_candidates(client, query, limit=1)
    return candidates[0] if candidates else None


def format_mmss(seconds: int) -> str:
    seconds = int(seconds or 0)
    m, s = divmod(seconds, 60)
    return f"{m}:{s:02d}"
