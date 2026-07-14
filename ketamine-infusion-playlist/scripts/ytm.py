"""Shared helpers for the ketamine-infusion-playlist skill.

Holds the runtime-state paths (auth file, exclude-list), the fixed phase
protocol, and small wrappers around ytmusicapi used by the other scripts.
Nothing in here is a CLI entrypoint on its own.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

STATE_DIR = Path.home() / ".local" / "share" / "ketamine-playlist"
AUTH_FILE = STATE_DIR / "browser.json"
EXCLUDE_FILE = STATE_DIR / "exclude-playlists.json"
EXCLUDE_TRACKS_FILE = STATE_DIR / "exclude-tracks.json"

# The fixed 50-minute, 3-phase protocol. Seconds are the target length of
# each phase; see references/phase-template.md for the full rationale.
PHASES = [
    {"name": "Build", "target_seconds": 35 * 60},
    {"name": "Peak", "target_seconds": 10 * 60},
    {"name": "Wind-down", "target_seconds": 5 * 60},
]
TOTAL_TARGET_SECONDS = sum(p["target_seconds"] for p in PHASES)  # 3000 = 50:00
PHASE_TOLERANCE_SECONDS = 90  # +/- warn threshold per phase, informational only

# Artist-diversity rule (whole playlist, except the Peak phase which is
# intentionally heavy on one artist e.g. Max Cooper).
MAX_TRACKS_PER_ARTIST = 3
DIVERSITY_EXEMPT_PHASE = "Peak"


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


def load_exclude_list() -> list[dict[str, str]]:
    if not EXCLUDE_FILE.exists():
        return []
    return json.loads(EXCLUDE_FILE.read_text())


def save_exclude_list(entries: list[dict[str, str]]) -> None:
    ensure_state_dir()
    EXCLUDE_FILE.write_text(json.dumps(entries, indent=2, ensure_ascii=False) + "\n")


def add_to_exclude_list(playlist_id: str, name: str) -> list[dict[str, str]]:
    entries = load_exclude_list()
    if not any(e["id"] == playlist_id for e in entries):
        entries.append({"id": playlist_id, "name": name})
        save_exclude_list(entries)
    return entries


def remove_from_exclude_list(playlist_ids: list[str]) -> list[dict[str, str]]:
    ids = set(playlist_ids)
    entries = [e for e in load_exclude_list() if e["id"] not in ids]
    save_exclude_list(entries)
    return entries


def get_excluded_video_ids(client) -> set[str]:
    """Union the videoIds of every playlist in the exclude-list, fetched live."""
    excluded: set[str] = set()
    for entry in load_exclude_list():
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
# Sibling to the playlist exclude-list above, deliberately keyed by "videoId" (not
# "id") so the two files' schemas stay visually distinguishable.

def load_exclude_tracks() -> list[dict[str, str]]:
    if not EXCLUDE_TRACKS_FILE.exists():
        return []
    return json.loads(EXCLUDE_TRACKS_FILE.read_text())


def save_exclude_tracks(entries: list[dict[str, str]]) -> None:
    ensure_state_dir()
    EXCLUDE_TRACKS_FILE.write_text(json.dumps(entries, indent=2, ensure_ascii=False) + "\n")


def add_to_exclude_tracks(video_id: str, name: str) -> list[dict[str, str]]:
    entries = load_exclude_tracks()
    if not any(e["videoId"] == video_id for e in entries):
        entries.append({"videoId": video_id, "name": name})
        save_exclude_tracks(entries)
    return entries


def get_excluded_track_video_ids() -> set[str]:
    """videoIds from the permanent per-track exclude file. No network needed."""
    return {e["videoId"] for e in load_exclude_tracks() if e.get("videoId")}


def get_all_excluded_video_ids(client) -> set[str]:
    """Union of (a) tracks in every excluded playlist and (b) the permanent
    per-track exclude list. This is what playlist-building should check
    against; get_excluded_video_ids() stays playlist-only for callers (like
    --sync) that need to subtract out a specific playlist's own tracks."""
    return get_excluded_video_ids(client) | get_excluded_track_video_ids()


# --- Instrumental-only enforcement ---
# Every track must be fully instrumental, except possibly a single final track
# that starts at/after VOCAL_EXCEPTION_START_SECONDS. Detection combines a hard
# lyrics-text signal (check_vocals) with a soft title heuristic
# (is_likely_vocal_title) -- per explicit user instruction, any confirmed
# lyrics is a hard block, "feat."-style titles are a flag, and a little extra
# slowness at creation time is worth it to avoid unexpected vocals mid-infusion.
VOCAL_EXCEPTION_START_SECONDS = 47 * 60  # 2820s
VOCAL_TITLE_MARKERS = ("feat.", "ft.", "featuring", "(feat", "(ft")
LYRICS_CACHE_FILE = STATE_DIR / "lyrics-cache.json"


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


def resolve_track(client, query: str) -> dict[str, Any] | None:
    """Resolve a free-text 'Artist - Title' query to a concrete track.

    Tries the "songs" filter first, falls back to "videos" (some tracks are
    only catalogued as videos on YouTube Music). Returns None if nothing
    reasonable comes back.
    """
    for filt in ("songs", "videos"):
        try:
            results = client.search(query, filter=filt, limit=5)
        except Exception:  # noqa: BLE001
            results = []
        if results:
            top = results[0]
            artists = top.get("artists") or []
            return {
                "query": query,
                "videoId": top.get("videoId"),
                "title": top.get("title"),
                "artist": artists[0]["name"] if artists else "Unknown",
                "duration_seconds": top.get("duration_seconds"),
                "matched_filter": filt,
            }
    return None


def format_mmss(seconds: int) -> str:
    seconds = int(seconds or 0)
    m, s = divmod(seconds, 60)
    return f"{m}:{s:02d}"
