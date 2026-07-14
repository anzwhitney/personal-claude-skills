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
    python3 build_playlist.py --plan plan.json --dry-run
    python3 build_playlist.py --plan plan.json
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
    add_to_exclude_list,
    format_mmss,
    get_client,
    get_excluded_video_ids,
    resolve_track,
)


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


def build_timeline(client, plan: dict) -> tuple[list[dict], list[str]]:
    """Resolve every track in the plan. Returns (resolved_phases, issues)."""
    excluded_ids = get_excluded_video_ids(client)
    phase_targets = {p["name"]: p["target_seconds"] for p in PHASES}

    resolved_phases = []
    issues: list[str] = []
    artist_counts: dict[str, int] = {}

    for phase_plan in plan["phases"]:
        name = phase_plan["name"]
        if name not in phase_targets:
            issues.append(f"unknown phase name {name!r}; expected one of {list(phase_targets)}")
        target = phase_plan.get("target_seconds", phase_targets.get(name, 0))

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

            resolved_tracks.append(track)

        phase_total = sum(t["duration_seconds"] or 0 for t in resolved_tracks)
        if abs(phase_total - target) > PHASE_TOLERANCE_SECONDS:
            issues.append(
                f"[{name}] duration {format_mmss(phase_total)} is off target "
                f"{format_mmss(target)} by more than {PHASE_TOLERANCE_SECONDS}s"
            )

        resolved_phases.append({"name": name, "target_seconds": target, "tracks": resolved_tracks, "total_seconds": phase_total})

    grand_total = sum(p["total_seconds"] for p in resolved_phases)
    if grand_total < TOTAL_TARGET_SECONDS:
        issues.append(
            f"TOTAL {format_mmss(grand_total)} is under the {format_mmss(TOTAL_TARGET_SECONDS)} minimum"
        )

    return resolved_phases, issues


def print_timeline(resolved_phases: list[dict], issues: list[str]) -> None:
    cumulative = 0
    print(f"{'Time':>8}  {'Phase':<10} Track")
    print("-" * 70)
    for phase in resolved_phases:
        print(f"{'':>8}  {'--- ' + phase['name'] + ' ---':<10}"
              f" (target {format_mmss(phase['target_seconds'])}, actual {format_mmss(phase['total_seconds'])})")
        for track in phase["tracks"]:
            print(f"{format_mmss(cumulative):>8}  {phase['name']:<10} {track['artist']} - {track['title']}"
                  f"  [{format_mmss(track['duration_seconds'])}]")
            cumulative += track["duration_seconds"] or 0
    print("-" * 70)
    print(f"{format_mmss(cumulative):>8}  TOTAL")

    if issues:
        print(f"\n{len(issues)} issue(s):")
        for issue in issues:
            print(f"  - {issue}")
    else:
        print("\nNo issues.")


def cmd_plan(client, plan_path: str, dry_run: bool) -> int:
    plan = json.loads(Path(plan_path).read_text())
    resolved_phases, issues = build_timeline(client, plan)
    print_timeline(resolved_phases, issues)

    blocking = [i for i in issues if "NOT FOUND" in i or "ALREADY USED" in i or "TOTAL" in i]
    if blocking:
        print("\nBlocking issues present (missing/reused tracks, or under 50:00). "
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
    parser.add_argument("--plan", metavar="PLAN_JSON", help="path to a curated track plan (see module docstring)")
    parser.add_argument("--dry-run", action="store_true", help="resolve and print the timeline, but create nothing")
    args = parser.parse_args()

    if not any([args.list_playlists, args.add_exclude, args.plan]):
        parser.error("one of --list-playlists, --add-exclude, or --plan is required")

    client = get_client()

    if args.list_playlists:
        return cmd_list_playlists(client)
    if args.add_exclude:
        return cmd_add_exclude(client, args.add_exclude)
    return cmd_plan(client, args.plan, args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
