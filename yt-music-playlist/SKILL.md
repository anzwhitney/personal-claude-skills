---
name: yt-music-playlist
description: Generic engine for building and editing a YouTube Music playlist from curated "Artist - Title" track queries via ytmusicapi. Handles auth, track search/resolution, timeline validation, playlist create/show/sync/finalize, no-reuse exclude-lists, and optional vocal/lyrics filtering. Use this directly for a plain "make me a YouTube Music playlist" request, or as the shared foundation another skill invokes with its own `--protocol` config (segment timing, artist-diversity caps, vocal policy) for a more specific playlist format — see ketamine-infusion-playlist for an example consumer. Not for playing music or browsing an existing library — only for building/editing playlists.
---

Build a YouTube Music playlist from a curated list of "Artist - Title" queries, resolving each
to a real track via `ytmusicapi`, validating the result, and creating (or editing) the playlist
once approved. This skill does not choose tracks — that's the curation step, done by Claude (or
a consuming skill) before handing a plan to `scripts/build_playlist.py`.

All scripts run via the dedicated venv's python:
`~/.local/share/yt-music-playlist/venv/bin/python3 scripts/<script>.py`. If that venv doesn't
exist yet, create it and install `requirements.txt` first (see
`references/ytmusicapi-guide.md`). Auth and the lyrics cache are shared across every consumer
of this skill; no-reuse exclude-lists are per-consumer (see `--exclude-dir` below).

## Optional protocol config

A specific playlist format (fixed segment timing, artist-diversity caps, an instrumental-only
rule, etc.) is expressed as a `--protocol PATH` JSON config, not code — see
`references/ytmusicapi-guide.md` for the full schema. Without `--protocol`, this skill builds
an unconstrained flat playlist: any phase names, no timing/diversity checks, vocal detection
off. A consuming skill (e.g. ketamine-infusion-playlist) supplies its own protocol file and
invokes this skill's `build_playlist.py` with it, alongside its own `--exclude-dir`.

## Workflow

1. **Preflight.** Ensure the venv exists and `ytmusicapi` is installed. Run
   `scripts/setup_auth.py` — it verifies existing auth with a live search, or walks the user
   through capturing browser headers if none exists yet or the existing ones are stale.

2. **Pick an exclude-dir.** Choose (or create) a directory to hold this playlist's no-reuse
   state — `exclude-playlists.json` (prior playlists whose tracks should never be reused) and
   `exclude-tracks.json` (individually banned tracks). A consuming skill should use its own
   fixed directory; for an ad hoc request, `~/.local/share/yt-music-playlist/default-excludes/`
   is a reasonable default. Pass it as `--exclude-dir DIR` to every command below.

3. **Seed the playlist exclude-list (first run only).** If `exclude-playlists.json` doesn't
   exist yet in the chosen dir, run `scripts/build_playlist.py --list-playlists`, show the user
   their library playlists, and ask which ones (if any) should be excluded from reuse. Add the
   chosen ones with `scripts/build_playlist.py --exclude-dir DIR --add-exclude ID [ID ...]`.
   Skip this step on later runs — the exclude-list persists. (`--remove-exclude ID [...]` undoes
   a mistaken add.)

4. **Manage the permanent track exclude-list.** Individual tracks the user dislikes or that
   don't fit in practice can be permanently banned regardless of which playlist they'd come
   from. `scripts/build_playlist.py --exclude-dir DIR --list-exclude-tracks` shows the current
   list; `--add-exclude-track "Artist - Title" [...]` adds to it.

5. **Curate.** Propose candidate tracks (as "Artist - Title" strings), honoring whatever
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

6. **Dry-run.** Run `scripts/build_playlist.py --exclude-dir DIR [--protocol PATH] --plan
   /tmp/plan.json --dry-run`. It resolves every track via ytmusicapi search; drops any not found
   or already used; flags any protocol violations (timing, diversity, vocals); and prints a full
   timeline with cumulative start times. Nothing is created yet. If a protocol's vocal policy is
   active, pass `--no-lyrics-check` for a faster timing-only iteration pass (the title heuristic
   still runs; network lyrics lookups are cached across runs).

7. **Iterate.** If there are blocking issues (not-found, already-used, a protocol violation) or
   the timeline doesn't look right, revise the plan file and re-run step 6. Show the user the
   timeline before creating anything.

8. **Create.** Once the user approves, run the same command without `--dry-run`. This creates
   the playlist (privacy/title/description from the protocol, or generic defaults without one)
   and adds the resolved tracks in order. **It is deliberately NOT added to the exclude-list
   yet** — a successful create doesn't mean the user is done, since they need to listen to it
   first. Report the playlist URL and final timeline back to the user, and tell them the next
   three steps.

9. **Review.** The user listens. If they want to inspect the live playlist's current contents
   (including `setVideoId`, needed for editing), run `scripts/build_playlist.py --show
   PLAYLIST_ID`.

10. **Sync edits.** If the user wants changes, edit the plan file and run
    `scripts/build_playlist.py --exclude-dir DIR [--protocol PATH] --sync PLAYLIST_ID --plan
    plan.json --dry-run` to preview, then without `--dry-run` to apply. This reconciles the live
    playlist to the plan (full remove-and-re-add in plan order) without treating the playlist's
    own current tracks as already-used. Repeat steps 9-10 as needed.

11. **Finalize.** Once the user explicitly confirms the playlist is done, run
    `scripts/build_playlist.py --exclude-dir DIR --finalize PLAYLIST_ID`. This is the only step
    that records the playlist in the exclude-list so its tracks aren't reused in a future
    playlist. Do not finalize on the user's behalf just because a create or sync succeeded.

For full ytmusicapi call details (auth setup, search/playlist API shapes, gotchas) and the
`--protocol` config schema, see `references/ytmusicapi-guide.md`.
