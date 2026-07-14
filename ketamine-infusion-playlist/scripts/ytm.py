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
