---
name: yt-music-playlist
description: Generic engine for building and editing a YouTube Music playlist from curated "Artist - Title" track queries via ytmusicapi. Handles auth, track search/resolution, timeline validation, playlist create/show/sync, and optional vocal/lyrics filtering. Use this directly for a plain "make me a YouTube Music playlist" request, or as the shared foundation another skill invokes with its own `--protocol` config (segment timing, artist-diversity caps, vocal policy) for a more specific playlist format — see ketamine-infusion-playlist for an example consumer. Not for playing music or browsing an existing library — only for building/editing playlists.
---

Build a YouTube Music playlist from a curated list of "Artist - Title" queries, resolving each
to a real track via `ytmusicapi`, validating the result, and creating (or editing) the playlist
once approved. This skill does not choose tracks — that's the curation step, done by Claude (or
a consuming skill) before handing a plan to `scripts/build_playlist.py`.

All scripts run via the dedicated venv's python:
`~/.local/share/yt-music-playlist/venv/bin/python3 scripts/<script>.py`. If that venv doesn't
exist yet, create it and install `requirements.txt` first (see
`references/ytmusicapi-guide.md`). Auth and the lyrics cache are shared across every consumer
of this skill.

## Optional protocol config

A specific playlist format (fixed segment timing, artist-diversity caps, an instrumental-only
rule, etc.) is expressed as a `--protocol PATH` JSON config, not code — see
`references/ytmusicapi-guide.md` for the full schema. Without `--protocol`, this skill builds
an unconstrained flat playlist: any phase names, no timing/diversity checks, vocal detection
off. A consuming skill (e.g. ketamine-infusion-playlist) supplies its own protocol file and
invokes this skill's `build_playlist.py` with it.

## Workflow

1. **Preflight.** Ensure the venv exists and `ytmusicapi` is installed. Run
   `scripts/setup_auth.py` — it verifies existing auth with a live search, or walks the user
   through capturing browser headers if none exists yet or the existing ones are stale.

2. **Curate.** Propose candidate tracks (as "Artist - Title" strings), honoring whatever
   protocol is in play (if any) plus the user's stated preferences. If a query's version is
   ambiguous (edits/remixes/features share a title) or you want to sanity-check a track before
   committing it, audition candidates with `scripts/search_tracks.py -n 5 "Artist - Title"`
   rather than guessing from the top search hit. Write the plan to a JSON file, e.g.
   `/tmp/plan.json`:

   ```json
   {
     "title": "My Playlist — <today's date>",
     "phases": [
       {"name": "Segment 1", "tracks": ["Artist - Title", "..."]}
     ],
     "vocal_ok": ["Artist - Title"]
   }
   ```

   A protocol-less playlist can use a single unnamed segment, e.g. `{"name": "Tracks", "tracks": [...]}`.
   `vocal_ok` is optional — a list of queries to manually clear if the vocal policy (if any)
   flags a verified false positive.

3. **Dry-run.** Run `scripts/build_playlist.py [--protocol PATH] --plan /tmp/plan.json
   --dry-run`. It resolves every track via ytmusicapi search and flags any protocol violations
   (timing, diversity, vocals), then prints a full timeline with cumulative start times. Nothing
   is created yet. If a protocol's vocal policy is active, pass `--no-lyrics-check` for a faster
   timing-only iteration pass (the title heuristic still runs; network lyrics lookups are
   cached across runs).

4. **Iterate.** If there are blocking issues (not-found, a protocol violation) or the timeline
   doesn't look right, revise the plan file and re-run step 3. Show the user the timeline before
   creating anything.

5. **Create.** Once the user approves, run the same command without `--dry-run`. This creates
   the playlist (privacy/title/description from the protocol, or generic defaults without one)
   and adds the resolved tracks in order. Report the playlist URL and final timeline back to the
   user.

6. **Review.** The user listens. If they want to inspect the live playlist's current contents
   (including `setVideoId`, needed for editing), run `scripts/build_playlist.py --show
   PLAYLIST_ID`.

7. **Sync edits.** If the user wants changes, edit the plan file and run
   `scripts/build_playlist.py [--protocol PATH] --sync PLAYLIST_ID --plan plan.json --dry-run`
   to preview, then without `--dry-run` to apply. This reconciles the live playlist to the plan
   (full remove-and-re-add in plan order). Repeat steps 6-7 as needed.

## Optional: avoid reusing tracks across playlists

By default this skill has no memory of past playlists — every run is independent, and nothing
above is added to any kind of exclude-list. Turn on no-reuse tracking only if the user asks not
to repeat tracks across playlists, or if a `--protocol` calls for it (e.g.
ketamine-infusion-playlist always uses this, so it never repeats a track from a prior session).

To opt in, pick (or have the consuming skill fix) a directory to hold this playlist's no-reuse
state — `exclude-playlists.json` (prior playlists whose tracks should never be reused) and
`exclude-tracks.json` (individually banned tracks). Either pass it as `--exclude-dir DIR` to
every command in the workflow above (steps 3, 5, 7), or — for a consuming skill that always
wants this on — bake it into that skill's `--protocol` config as `"exclude_dir"` so it never has
to pass `--exclude-dir` itself (see `references/ytmusicapi-guide.md`); `--exclude-dir` on the
command line overrides a protocol's value if both are given. With an exclude-dir in effect,
from either source:

- **Seed the playlist exclude-list (first run only).** If `exclude-playlists.json` doesn't
  exist yet in that dir, run `scripts/build_playlist.py --list-playlists`, show the user their
  library playlists, and ask which ones (if any) should be excluded from reuse. Add the chosen
  ones with `scripts/build_playlist.py --exclude-dir DIR --add-exclude ID [ID ...]`
  (`--remove-exclude ID [...]` undoes a mistaken add). Skip this on later runs — it persists.
- **Manage the permanent track exclude-list.** Individual tracks the user dislikes or that
  don't fit in practice can be permanently banned regardless of which playlist they'd come
  from: `scripts/build_playlist.py --exclude-dir DIR --list-exclude-tracks` /
  `--add-exclude-track "Artist - Title" [...]`.
- **Dry-run/create/sync** (steps 3/5/7) will then drop any track already used (by playlist or
  by the permanent track exclude-list) and flag it as an issue.
- **Finalize.** Once the user explicitly confirms a created playlist is done, run
  `scripts/build_playlist.py --exclude-dir DIR --finalize PLAYLIST_ID`. This is the only step
  that records the playlist in the exclude-list so its tracks aren't reused in a future
  playlist. Do not finalize on the user's behalf just because a create or sync succeeded.

For full ytmusicapi call details (auth setup, search/playlist API shapes, gotchas) and the
`--protocol` config schema, see `references/ytmusicapi-guide.md`.
