#!/usr/bin/env python3
"""Resolve a curated track plan, validate it, and (optionally) create the
unlisted YouTube Music playlist.

This script does NOT choose tracks — that's done by Claude during curation,
per references/phase-template.md and references/curation-notes.md. This
script's job is mechanical: resolve queries to real tracks, enforce the
no-reuse and artist-diversity rules, report a timeline, and create the
playlist once the user approves.

Plan file format (JSON):
{
  "title": "Ketamine Session -- 2026-07-13",
  "phases": [
    {"name": "Build", "tracks": ["Artist - Title", ...]},
    {"name": "Peak", "tracks": [...]},
    {"name": "Wind-down", "tracks": [...]}
  ]
}
Phase names must match ytm.PHASES. target_seconds come from ytm.PHASES;
override per-phase by adding a "target_seconds" key in the plan if needed.

Usage:
    python3 build_playlist.py --list-playlists
    python3 build_playlist.py --add-exclude PLxxxx PLyyyy
    python3 build_playlist.py --add-exclude-track "Artist - Title" [...]
    python3 build_playlist.py --list-exclude-tracks
    python3 build_playlist.py --plan plan.json --dry-run
    python3 build_playlist.py --plan plan.json --dry-run --no-lyrics-check
    python3 build_playlist.py --plan plan.json

Every track must be fully instrumental (no lyrics), except possibly a single
final track that starts at/after the 47:00 mark -- see VOCAL_EXCEPTION_START_SECONDS
in ytm.py. A plan may include a top-level "vocal_ok": ["query", ...] list to
manually clear a query that the heuristics flag as a false positive.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from ytm import (
    DIVERSITY_EXEMPT_PHASE,
    MAX_TRACKS_PER_ARTIST,
    PHASE_TOLERANCE_SECONDS,
    PHASES,
    TOTAL_TARGET_SECONDS,
    VOCAL_EXCEPTION_START_SECONDS,
    add_to_exclude_list,
    add_to_exclude_tracks,
    check_vocals,
    format_mmss,
    get_all_excluded_video_ids,
    get_client,
    is_likely_vocal_title,
    load_exclude_tracks,
    resolve_track,
)


BLOCKING_MARKERS = ("NOT FOUND", "ALREADY USED", "TOTAL", "STARTS AFTER 50:00", "HAS VOCALS")


def blocking_issues(issues: list[str]) -> list[str]:
    return [i for i in issues if any(m in i for m in BLOCKING_MARKERS)]


def cmd_list_playlists(client) -> int:
    playlists = client.get_library_playlists(limit=None)
    print(json.dumps(
        [{"playlistId": p["playlistId"], "title": p["title"], "count": p.get("count")} for p in playlists],
        indent=2, ensure_ascii=False,
    ))
    return 0


def cmd_add_exclude(client, playlist_ids: list[str]) -> int:
    for pid in playlist_ids:
        playlist = client.get_playlist(pid, limit=1)
        name = playlist.get("title", pid)
        add_to_exclude_list(pid, name)
        print(f"Added to exclude-list: {pid} ({name!r})")
    return 0


def cmd_add_exclude_track(client, queries: list[str]) -> int:
    for q in queries:
        track = resolve_track(client, q)
        if track is None:
            print(f"NOT FOUND (not added): {q!r}")
            continue
        name = f"{track['artist']} - {track['title']}"
        add_to_exclude_tracks(track["videoId"], name)
        print(f"Added to track exclude-list: {track['videoId']} ({name!r})")
    return 0


def cmd_list_exclude_tracks() -> int:
    print(json.dumps(load_exclude_tracks(), indent=2, ensure_ascii=False))
    return 0


def _apply_vocal_checks(
    client,
    resolved_phases: list[dict],
    issues: list[str],
    check_lyrics: bool,
    vocal_ok_queries: set[str],
) -> None:
    """Enforce the instrumental-only rule across the whole resolved playlist.

    Every track must be vocal-free, except possibly the single final track in
    the playlist if it starts at/after VOCAL_EXCEPTION_START_SECONDS (47:00).
    A plan may mark a query in a top-level "vocal_ok" list to manually
    downgrade a confirmed-lyrics block to advisory (verified false positive).
    """
    all_tracks = [(phase, track) for phase in resolved_phases for track in phase["tracks"]]
    if not all_tracks:
        return
    last_track = all_tracks[-1][1]

    for phase, track in all_tracks:
        label = f"{track['artist']} - {track['title']!r} at {format_mmss(track['start_seconds'])}"
        override = track.get("query") in vocal_ok_queries
        allowed_vocal_slot = (
            track is last_track and (track["start_seconds"] or 0) >= VOCAL_EXCEPTION_START_SECONDS
        )

        has_lyrics = check_vocals(client, track["videoId"]) if check_lyrics and track["videoId"] else None

        if has_lyrics is True:
            if override:
                issues.append(f"[{phase['name']}] vocal_ok override (confirmed lyrics ignored): {label}")
            elif allowed_vocal_slot:
                issues.append(f"[{phase['name']}] vocal closer (allowed, starts >= 47:00): {label}")
            else:
                issues.append(f"[{phase['name']}] HAS VOCALS (instrumental rule): {label}")
        elif has_lyrics is None and check_lyrics:
            issues.append(f"[{phase['name']}] could not verify lyrics (advisory): {label}")

        if is_likely_vocal_title(track) and has_lyrics is not True and not override:
            note = "likely vocal (title)" if allowed_vocal_slot else "likely vocal (title) -- verify before use"
            issues.append(f"[{phase['name']}] {note}: {label}")


def build_timeline(client, plan: dict, check_lyrics: bool = True) -> tuple[list[dict], list[str]]:
    """Resolve every track in the plan. Returns (resolved_phases, issues).

    Each track gets a cumulative "start_seconds" (its position from the top
    of the playlist, not just its own duration). The only hard timing rule
    is that no track may *start* at/after TOTAL_TARGET_SECONDS (50:00) --
    the playlist itself may run well past that, since the clinician fades
    the music out around 50:00 regardless of what's queued after it.
    """
    excluded_ids = get_all_excluded_video_ids(client)
    phase_targets = {p["name"]: p["target_seconds"] for p in PHASES}

    resolved_phases = []
    issues: list[str] = []
    artist_counts: dict[str, int] = {}
    cumulative = 0

    for phase_plan in plan["phases"]:
        name = phase_plan["name"]
        if name not in phase_targets:
            issues.append(f"unknown phase name {name!r}; expected one of {list(phase_targets)}")
        target = phase_plan.get("target_seconds", phase_targets.get(name, 0))
        phase_start = cumulative

        resolved_tracks = []
        prev_artist = None
        for query in phase_plan.get("tracks", []):
            track = resolve_track(client, query)
            if track is None:
                issues.append(f"[{name}] NOT FOUND: {query!r}")
                continue
            if track["videoId"] in excluded_ids:
                issues.append(f"[{name}] ALREADY USED (skipped): {track['artist']} - {track['title']!r}")
                continue

            artist = track["artist"]
            if name != DIVERSITY_EXEMPT_PHASE:
                if artist == prev_artist:
                    issues.append(f"[{name}] consecutive same-artist tracks: {artist!r}")
                artist_counts[artist] = artist_counts.get(artist, 0) + 1
                if artist_counts[artist] == MAX_TRACKS_PER_ARTIST + 1:
                    issues.append(f"artist {artist!r} exceeds cap of {MAX_TRACKS_PER_ARTIST} tracks/playlist")
            prev_artist = artist

            if cumulative >= TOTAL_TARGET_SECONDS:
                issues.append(
                    f"[{name}] STARTS AFTER 50:00: {track['artist']} - {track['title']!r} "
                    f"starts at {format_mmss(cumulative)}"
                )

            track["start_seconds"] = cumulative
            resolved_tracks.append(track)
            cumulative += track["duration_seconds"] or 0

        phase_total = sum(t["duration_seconds"] or 0 for t in resolved_tracks)

        if name == "Wind-down":
            # Content past 50:00 is irrelevant to length (the clinician fades
            # the music out around then), so only count the portion of this
            # phase that falls before the 50:00 boundary -- and only flag a
            # shortfall, never an overflow.
            effective_total = max(0, min(phase_total, TOTAL_TARGET_SECONDS - phase_start))
            if effective_total < target - PHASE_TOLERANCE_SECONDS:
                issues.append(
                    f"[{name}] duration {format_mmss(effective_total)} (before 50:00) is under target "
                    f"{format_mmss(target)} by more than {PHASE_TOLERANCE_SECONDS}s"
                )
        elif abs(phase_total - target) > PHASE_TOLERANCE_SECONDS:
            issues.append(
                f"[{name}] duration {format_mmss(phase_total)} is off target "
                f"{format_mmss(target)} by more than {PHASE_TOLERANCE_SECONDS}s"
            )

        resolved_phases.append({
            "name": name,
            "target_seconds": target,
            "tracks": resolved_tracks,
            "total_seconds": phase_total,
            "start_seconds": phase_start,
        })

    grand_total = cumulative
    if grand_total < TOTAL_TARGET_SECONDS:
        issues.append(
            f"TOTAL {format_mmss(grand_total)} is under the {format_mmss(TOTAL_TARGET_SECONDS)} minimum"
        )

    vocal_ok_queries = set(plan.get("vocal_ok", []))
    _apply_vocal_checks(client, resolved_phases, issues, check_lyrics, vocal_ok_queries)

    return resolved_phases, issues


def print_timeline(resolved_phases: list[dict], issues: list[str]) -> None:
    print(f"{'Time':>8}  {'Phase':<10} Track")
    print("-" * 70)
    total = 0
    for phase in resolved_phases:
        print(f"{'':>8}  {'--- ' + phase['name'] + ' ---':<10}"
              f" (target {format_mmss(phase['target_seconds'])}, actual {format_mmss(phase['total_seconds'])})")
        for track in phase["tracks"]:
            print(f"{format_mmss(track['start_seconds']):>8}  {phase['name']:<10} {track['artist']} - {track['title']}"
                  f"  [{format_mmss(track['duration_seconds'])}]")
            total = track["start_seconds"] + (track["duration_seconds"] or 0)
    print("-" * 70)
    print(f"{format_mmss(total):>8}  TOTAL")

    if issues:
        print(f"\n{len(issues)} issue(s):")
        for issue in issues:
            print(f"  - {issue}")
    else:
        print("\nNo issues.")


def cmd_plan(client, plan_path: str, dry_run: bool, check_lyrics: bool = True) -> int:
    plan = json.loads(Path(plan_path).read_text())
    resolved_phases, issues = build_timeline(client, plan, check_lyrics=check_lyrics)
    print_timeline(resolved_phases, issues)

    blocking = blocking_issues(issues)
    if blocking:
        print("\nBlocking issues present (missing/reused/vocal tracks, timing violations). "
              "Revise the plan and re-run before creating." if not dry_run else
              "\n(Dry run only shown above; resolve blocking issues before a live create.)")
        if not dry_run:
            return 1

    if dry_run:
        print("\nDry run only -- nothing was created.")
        return 0

    title = plan.get("title") or f"Ketamine Session — {date.today().isoformat()}"
    all_video_ids = [t["videoId"] for phase in resolved_phases for t in phase["tracks"]]

    playlist_id = client.create_playlist(
        title=title,
        description="Generated by ketamine-infusion-playlist skill.",
        privacy_status="UNLISTED",
    )
    client.add_playlist_items(playlist_id, videoIds=all_video_ids, duplicates=True)
    add_to_exclude_list(playlist_id, title)

    print(f"\nCreated playlist: {title}")
    print(f"URL: https://music.youtube.com/playlist?list={playlist_id}")
    print(f"({len(all_video_ids)} tracks added; playlist ID recorded in exclude-list for future runs.)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--list-playlists", action="store_true", help="list library playlists as JSON, then exit")
    parser.add_argument("--add-exclude", nargs="+", metavar="PLAYLIST_ID", help="add playlist id(s) to the exclude-list, then exit")
    parser.add_argument("--add-exclude-track", nargs="+", metavar="QUERY", help='resolve and permanently exclude track(s), e.g. "Artist - Title"')
    parser.add_argument("--list-exclude-tracks", action="store_true", help="print the permanent track exclude-list, then exit")
    parser.add_argument("--plan", metavar="PLAN_JSON", help="path to a curated track plan (see module docstring)")
    parser.add_argument("--dry-run", action="store_true", help="resolve and print the timeline, but create nothing")
    parser.add_argument("--no-lyrics-check", action="store_true", help="skip network lyrics lookups (title heuristic still runs); use for fast timing-only iteration")
    args = parser.parse_args()

    if not any([args.list_playlists, args.add_exclude, args.add_exclude_track, args.list_exclude_tracks, args.plan]):
        parser.error(
            "one of --list-playlists, --add-exclude, --add-exclude-track, "
            "--list-exclude-tracks, or --plan is required"
        )

    client = get_client()

    if args.list_playlists:
        return cmd_list_playlists(client)
    if args.add_exclude:
        return cmd_add_exclude(client, args.add_exclude)
    if args.add_exclude_track:
        return cmd_add_exclude_track(client, args.add_exclude_track)
    if args.list_exclude_tracks:
        return cmd_list_exclude_tracks()
    return cmd_plan(client, args.plan, args.dry_run, check_lyrics=not args.no_lyrics_check)


if __name__ == "__main__":
    sys.exit(main())
