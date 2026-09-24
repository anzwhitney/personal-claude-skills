#!/usr/bin/env python3
"""Analyze the audio content of YouTube Music tracks during curation.

Advisory companion to search_tracks.py: resolves tracks, then prints a
compact per-track audio summary so candidates can be judged on how they
actually sound, not just on metadata. Features are cached by videoId (see
audio.py), so re-running on already-analyzed tracks is instant; a cache miss
downloads the audio, analyzes it (~10-20s per track) and deletes it.

Summary columns:
  voc%   share of the track where a voice is detected (any voice, including
         wordless or sampled vocals -- not just lyrics)
  ar     arousal/energy, 1-9 (higher = more energetic)
  rlx    probability the track reads as "relaxed", 0-1
  LU     integrated loudness (LUFS)
  s>e    loudness at the start > end (short-term LUFS over the edge 30s)
  bpm    tempo ("?" = low-confidence estimate, common for ambient)
  key    Camelot code (e.g. 8A); adjacent numbers/letters mix smoothly
  styles top Discogs styles the audio resembles (full list with --json)

--similar-to ranks by how alike the tracks' style profiles are (0-1). It
measures sound/texture, not artist: an artist's ambient track can sit closer
to another artist's ambient track than to its own techno.

Usage:
    python3 analyze_tracks.py "Max Cooper - Repeat" "Nils Frahm - Says"
    python3 analyze_tracks.py --plan plan.json [--transitions]
    python3 analyze_tracks.py --playlist PLxxxx
    python3 analyze_tracks.py --similar-to "Max Cooper - Repeat" "Candidate A - X" "Candidate B - Y"
    python3 analyze_tracks.py --json 9GAEx0WpkG8

Positional arguments are "Artist - Title" queries, or bare 11-character
videoIds. With --plan, tracks are taken from the plan in order (phase
headings included); --transitions then also reports each adjacent pair.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from audio import (
    FeatureSource,
    audio_unavailable_reason,
    style_similarity,
    summary_columns,
    transition,
)
from ytm import get_client, resolve_track

VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")


def resolve_items(client, queries: list[str]) -> list[dict]:
    items = []
    for q in queries:
        if VIDEO_ID_RE.match(q):
            items.append({"videoId": q, "label": q})
            continue
        track = resolve_track(client, q)
        if track is None:
            print(f"NOT FOUND: {q!r}", file=sys.stderr)
            continue
        items.append({"videoId": track["videoId"], "label": f"{track['artist']} - {track['title']}"})
    return items


def plan_items(client, plan_path: str) -> list[dict]:
    plan = json.loads(Path(plan_path).read_text())
    items = []
    for phase in plan.get("phases") or plan.get("segments") or []:
        for item in resolve_items(client, phase.get("tracks", [])):
            items.append({**item, "phase": phase["name"]})
    return items


def playlist_items(client, playlist_id: str) -> list[dict]:
    playlist = client.get_playlist(playlist_id, limit=None)
    items = []
    for t in playlist.get("tracks", []):
        if not t.get("videoId"):
            continue
        artists = t.get("artists") or []
        artist = artists[0]["name"] if artists else "Unknown"
        items.append({"videoId": t["videoId"], "label": f"{artist} - {t.get('title')}"})
    return items


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("tracks", nargs="*", metavar="TRACK", help='"Artist - Title" query or videoId')
    parser.add_argument("--plan", metavar="PLAN_JSON", help="analyze every track in a plan, in order")
    parser.add_argument("--playlist", metavar="PLAYLIST_ID", help="analyze every track in a live playlist")
    parser.add_argument("--similar-to", metavar="TRACK", help="rank the other tracks by sonic similarity to this one")
    parser.add_argument("--transitions", action="store_true", help="also report each adjacent pair (loudness rise, arousal change, tempo, key)")
    parser.add_argument("--json", action="store_true", help="print full feature dicts as JSON instead of the table")
    parser.add_argument("--refresh", action="store_true", help="re-analyze even if cached")
    args = parser.parse_args()

    if not (args.tracks or args.plan or args.playlist):
        parser.error("give track queries/videoIds, --plan, or --playlist")
    reason = audio_unavailable_reason()
    if reason:
        print(reason, file=sys.stderr)
        return 3

    client = get_client()
    items = resolve_items(client, args.tracks)
    if args.plan:
        items += plan_items(client, args.plan)
    if args.playlist:
        items += playlist_items(client, args.playlist)
    ref = None
    if args.similar_to:
        refs = resolve_items(client, [args.similar_to])
        if not refs:
            return 2
        ref = refs[0]

    source = FeatureSource(refresh=args.refresh)
    for item in ([ref] if ref else []) + items:
        feats, err = source.get(item["videoId"], item["label"])
        item["features"], item["error"] = feats, err
        if feats and item["label"] == item["videoId"] and feats.get("label"):
            item["label"] = feats["label"]
        if len(items) > 3 and not args.json:
            print(f"  analyzed {item['label']}" + (f" (FAILED: {err})" if err else ""), file=sys.stderr)

    if ref:
        for item in items:
            item["similarity"] = style_similarity(ref["videoId"], item["videoId"]) if item["features"] else None
        items.sort(key=lambda i: -1 if i["similarity"] is None else i["similarity"], reverse=True)

    pairs = []
    if args.transitions:
        for a, b in zip(items, items[1:]):
            if a["features"] and b["features"]:
                pairs.append({"from": a["label"], "to": b["label"], **transition(a["features"], b["features"])})

    if args.json:
        out = {"tracks": [{k: v for k, v in i.items()} for i in items]}
        if ref:
            out["reference"] = ref
        if args.transitions:
            out["transitions"] = pairs
        print(json.dumps(out, indent=2, ensure_ascii=False))
    else:
        if ref:
            print(f"Reference: {summary_columns(ref['features'])}  {ref['label']}\n")
        phase = None
        for item in items:
            if item.get("phase") and item["phase"] != phase:
                phase = item["phase"]
                print(f"--- {phase} ---")
            sim = f"sim{item['similarity']:5.2f} " if item.get("similarity") is not None else ("sim   ?  " if ref else "")
            err = f"  [{item['error']}]" if item["error"] else ""
            print(f"{sim}{summary_columns(item['features'])}  {item['label']}{err}")
        if pairs:
            print("\nTransitions (next start vs previous track's level in LU, arousal change, tempo ratio, Camelot key steps):")
            for p in pairs:
                tempo = "?" if p["tempo_ratio"] is None else f"{p['tempo_ratio']:.2f}"
                keyd = "?" if p["key_distance"] is None else p["key_distance"]
                jump = "?" if p["loudness_rise_lu"] is None else f"{p['loudness_rise_lu']:+.1f}"
                print(f"  {jump:>6}LU  ar{p['arousal_delta']:+5.1f}  tempo {tempo:>4}  key {keyd}  "
                      f"{p['from']}  ->  {p['to']}")

    failed = [i for i in items if i["error"]]
    return 2 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
