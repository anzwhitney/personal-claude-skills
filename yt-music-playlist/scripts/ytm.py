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
import re
import unicodedata
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


# --- Track identity across videoIds ---
# The same recording can appear under several videoIds (an album track and
# its single, a re-upload), so "already used" can't rely on videoId alone.
# track_key() names a recording by its first artist, base title and version
# tags; lengths that differ by more than SAME_LENGTH_TOLERANCE_S mark a
# different cut of the same name (an unlabeled edit or live take).
SAME_LENGTH_TOLERANCE_S = 5
_QUALIFIER_RE = re.compile(r"\(([^()]*)\)|\[([^\[\]]*)\]")
_FEAT_RE = re.compile(r"\s(?:feat\.?|ft\.?|featuring)\s.*$", re.IGNORECASE)
# Qualifiers that label a release, not a different recording.
_IGNORED_QUALIFIER_RE = re.compile(
    r"^(?:(?:\d{4} )?(?:digital(?:ly)? )?remaster(?:ed)?(?: \d{4})?(?: version)?"
    r"|album version|original mix|official (?:music )?(?:audio|video)|audio)$")


def _fold(text: str) -> str:
    """Lowercase, strip accents and punctuation, collapse whitespace."""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = text.casefold().replace("&", " and ")
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text).split())


def track_key(artist: str, title: str) -> str:
    """Identity of a recording: "artist|base title|version tags".

    Bracketed qualifiers, a trailing " - qualifier" and a "feat. X" clause
    become version tags, so "Origins (Extended)" and "Repetition (feat. James
    Yorkston)" stay distinct from "Origins" and "Repetition", while
    "Flown - Remastered 2021" matches "Flown". Only the first artist counts,
    because YouTube Music lists guest artists inconsistently between releases.
    """
    tags = []
    for m in _QUALIFIER_RE.finditer(title):
        tags.append(m.group(1) if m.group(1) is not None else m.group(2))
    base = _QUALIFIER_RE.sub(" ", title)
    base, dash, suffix = base.partition(" - ")
    if dash:
        tags.append(suffix)
    feat = _FEAT_RE.search(base)
    if feat:
        tags.append(feat.group(0))
        base = base[:feat.start()]
    folded = sorted({t for t in map(_fold, tags) if t and not _IGNORED_QUALIFIER_RE.match(t)})
    first_artist = re.split(r",| & ", artist, maxsplit=1)[0]
    return f"{_fold(first_artist)}|{_fold(base)}|{','.join(folded)}"


def label_key(label: str) -> str:
    """track_key() of an "Artist - Title" label (split at the first " - ")."""
    artist, _, title = label.partition(" - ")
    return track_key(artist, title)


def same_length(a: int | None, b: int | None) -> bool:
    """True if two durations match, or either is unknown."""
    return a is None or b is None or abs(a - b) <= SAME_LENGTH_TOLERANCE_S


class UsedTracks:
    """Tracks that must not be reused, matched by videoId or by recording.

    match() returns ("same", entry) for the same videoId, or the same
    track_key() at the same length; ("version", entry) for the same key at a
    different length, which is worth a listen but may be a different cut;
    or None.
    """

    def __init__(self) -> None:
        self.by_id: dict[str, dict[str, Any]] = {}
        self.by_key: dict[str, list[dict[str, Any]]] = {}

    def add(self, video_id: str | None, artist: str, title: str,
            duration_seconds: int | None = None, source: str | None = None) -> None:
        entry = {"videoId": video_id, "label": f"{artist} - {title}",
                 "duration_seconds": duration_seconds, "source": source}
        if video_id:
            self.by_id.setdefault(video_id, entry)
        self.by_key.setdefault(track_key(artist, title), []).append(entry)

    def add_track(self, track: dict[str, Any], source: str | None = None) -> None:
        """Add a ytmusicapi playlist track, or a resolve_track() result."""
        if "artist" in track:
            artist = track["artist"]
        else:
            artists = track.get("artists") or []
            artist = artists[0]["name"] if artists else "Unknown"
        self.add(track.get("videoId"), artist, track.get("title") or "",
                 track.get("duration_seconds"), source)

    def without(self, video_ids: set[str]) -> "UsedTracks":
        """A copy minus every entry with one of these videoIds (for --sync,
        where a playlist's own tracks aren't "used" by itself)."""
        copy = UsedTracks()
        for key, entries in self.by_key.items():
            kept = [e for e in entries if e["videoId"] not in video_ids]
            if kept:
                copy.by_key[key] = kept
        copy.by_id = {v: e for v, e in self.by_id.items() if v not in video_ids}
        return copy

    def match(self, video_id: str | None, artist: str, title: str,
              duration_seconds: int | None = None) -> tuple[str, dict[str, Any]] | None:
        if video_id and video_id in self.by_id:
            return "same", self.by_id[video_id]
        entries = self.by_key.get(track_key(artist, title), [])
        for entry in entries:
            if same_length(entry["duration_seconds"], duration_seconds):
                return "same", entry
        return ("version", entries[0]) if entries else None


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
