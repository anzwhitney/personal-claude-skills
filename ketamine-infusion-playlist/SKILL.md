---
name: ketamine-infusion-playlist
description: Build a curated YouTube Music playlist timed to the phases of a ketamine infusion session (medically supervised, treatment-resistant depression). Use this whenever the user asks for a "ketamine playlist", "infusion playlist", to "build my ketamine music", or references their ketamine/infusion sessions and wants music. Uses the shared yt-music-playlist skill (ytmusicapi) to search real tracks and create an unlisted playlist on YouTube Music, following a fixed 50-minute, 3-phase protocol (Build / Peak / Wind-down) and never reusing tracks from prior session playlists.
---

Build a 50-minute YouTube Music playlist (40 min active infusion + 10 min comedown) for a
ketamine infusion session, following the fixed 3-phase protocol in
`references/phase-template.md` and encoded in `protocol.json`: **Build** (0:00-35:00,
intensifying ambient/downtempo), **Peak** (35:00-45:00, immersive melodic electronic anchored
on Max Cooper), **Wind-down** (45:00-50:00+, gentle emergent closers). Read
`references/phase-template.md` and `references/curation-notes.md` before curating tracks — they
hold the full character description per phase and notes from prior sessions.

This skill is a thin layer of curation policy on top of the generic **`yt-music-playlist`**
skill, which does all the mechanical work (auth, track search/resolution, timeline validation,
playlist create/show/sync/finalize). This skill contributes no code of its own — only
`protocol.json` (the fixed phase/diversity/vocal-policy config) and the curation reference docs
below. Every command in this workflow invokes the shared skill's `build_playlist.py` with
`--protocol protocol.json` and this skill's own `--exclude-dir`.

Define these once per session:
```
PY=~/.local/share/yt-music-playlist/venv/bin/python3
ENGINE=~/.claude/skills/yt-music-playlist/scripts/build_playlist.py
KTM=~/.claude/skills/ketamine-infusion-playlist
EXCLUDE_DIR=~/.local/share/ketamine-playlist
```
If the shared venv doesn't exist yet, create it and install the shared skill's
`requirements.txt` first (see `yt-music-playlist`'s `references/ytmusicapi-guide.md`).

## Hard rules

- **Instrumental only.** Every track must have no lyrics at all, except possibly a single
  final track that *starts* at/after 47:00 (a deliberate vocal closer). Enforced by
  `protocol.json`'s `vocal_policy` (mode `block`, exception after 47:00, last slot only) —
  don't rely on curation judgment alone.
- **Timing.** The playlist may run well past 50:00 — the clinician fades the music out around
  then regardless of what's queued. The only hard rule is that no track may *start* at/after
  50:00; only the portion of Wind-down before 50:00 counts toward its length target.
  (`protocol.json`: `total_target_seconds` 3000, Wind-down's `count_to_boundary_only`.)

## Workflow

1. **Preflight.** Ensure the shared venv exists and `ytmusicapi` is installed. Run
   `$PY $(dirname $ENGINE)/setup_auth.py` — it verifies existing auth with a live search, or
   walks the user through capturing browser headers if none exists yet or the existing ones are
   stale. (Auth is account-level and shared with any other playlist skill built on
   `yt-music-playlist`.)

2. **Seed the playlist exclude-list (first run only).** If `$EXCLUDE_DIR/exclude-playlists.json`
   doesn't exist yet, run `$PY $ENGINE --list-playlists`, show the user their library playlists,
   and ask which ones (if any) are prior ketamine-session playlists whose tracks should never be
   reused. Add the chosen ones with `$PY $ENGINE --exclude-dir $EXCLUDE_DIR --add-exclude ID
   [ID ...]`. Skip this step on later runs — the exclude-list persists. (`--remove-exclude ID
   [...]` undoes a mistaken add.)

3. **Manage the permanent track exclude-list.** Separately from playlists, individual tracks
   the user dislikes or that don't fit in practice can be permanently banned regardless of
   which playlist they'd come from. `$PY $ENGINE --exclude-dir $EXCLUDE_DIR
   --list-exclude-tracks` shows the current list; `--add-exclude-track "Artist - Title" [...]`
   adds to it. If the user mentions a track they don't want to hear again, add it here rather
   than noting it in prose.

4. **Curate.** Propose candidate tracks for each phase (as "Artist - Title" strings), honoring
   the phase-template's character descriptions, `curation-notes.md`, the diversity rule (prefer
   non-consecutive artists; cap ~2-3 tracks per artist per playlist, except the
   Max-Cooper-heavy Peak), and the instrumental-only hard rule above. If a query's version is
   ambiguous (edits/remixes/features share a title) or you want to sanity-check the vocal
   status of a track before committing it, audition candidates with
   `$PY $(dirname $ENGINE)/search_tracks.py -n 5 "Artist - Title"` rather than guessing from the
   top search hit. Don't worry about resolving exact runtimes by hand — the next step checks
   that mechanically. Write the plan to a JSON file, e.g. `/tmp/ktm-plan.json`:

   ```json
   {
     "title": "Ketamine Session — <today's date>",
     "phases": [
       {"name": "Build", "tracks": ["Artist - Title", "..."]},
       {"name": "Peak", "tracks": ["Max Cooper - ...", "..."]},
       {"name": "Wind-down", "tracks": ["Artist - Title", "..."]}
     ],
     "vocal_ok": ["Artist - Title"]
   }
   ```

   `vocal_ok` is optional — a list of queries to manually clear if the automated vocal check
   flags a verified false positive.

5. **Dry-run.** Run `$PY $ENGINE --protocol $KTM/protocol.json --exclude-dir $EXCLUDE_DIR --plan
   /tmp/ktm-plan.json --dry-run`. It resolves every track via ytmusicapi search; drops any not
   found or already used (by playlist or by the permanent track exclude-list); flags diversity,
   timing, and instrumental-rule issues (all per `protocol.json`); and prints a full timeline
   with cumulative start times. Nothing is created yet. The instrumental check makes real
   lyrics-lookup network calls (cached across runs) — pass `--no-lyrics-check` for a faster
   timing-only iteration pass (the title heuristic still runs).

6. **Iterate.** If there are blocking issues (not-found, already-used, a track starting at/after
   50:00, confirmed vocals, or total under 50:00) or the timeline doesn't look right, revise the
   plan file and re-run step 5. Show the user the timeline before creating anything.

7. **Create.** Once the user approves, run the same command without `--dry-run`. This creates
   an **unlisted** playlist titled with the date (per `protocol.json`'s `title_prefix` /
   `privacy_status`) and adds the resolved tracks in phase order. **It is deliberately NOT added
   to the exclude-list yet** — a successful create doesn't mean the user is done, since they
   need to listen to it first. Report the playlist URL and final timeline back to the user, and
   tell them the next three steps.

8. **Review.** The user listens. If they want to inspect the live playlist's current contents
   (including `setVideoId`, needed for editing), run `$PY $ENGINE --show PLAYLIST_ID`.

9. **Sync edits.** If the user wants changes, edit the plan file and run
   `$PY $ENGINE --protocol $KTM/protocol.json --exclude-dir $EXCLUDE_DIR --sync PLAYLIST_ID
   --plan plan.json --dry-run` to preview, then without `--dry-run` to apply. This reconciles
   the live playlist to the plan (full remove-and-re-add in plan order) without treating the
   playlist's own current tracks as already-used. Repeat steps 8-9 as needed.

10. **Finalize.** Once the user explicitly confirms the playlist is done, run
    `$PY $ENGINE --exclude-dir $EXCLUDE_DIR --finalize PLAYLIST_ID`. This is the only step that
    records the playlist in the exclude-list so its tracks aren't reused in a future session. Do
    not finalize on the user's behalf just because a create or sync succeeded.

11. **Optional follow-up.** If the user mentions standout tracks or things that didn't work
    after a session, append a short note to `references/curation-notes.md` for next time (and
    consider whether a disliked track belongs in the permanent track exclude-list, step 3).

For full ytmusicapi call details (auth setup, search/playlist API shapes, gotchas) and the
`protocol.json` schema, see the shared `yt-music-playlist` skill's
`references/ytmusicapi-guide.md`.
