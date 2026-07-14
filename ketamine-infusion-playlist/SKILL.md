---
name: ketamine-infusion-playlist
description: Build a curated YouTube Music playlist timed to the phases of a ketamine infusion session (medically supervised, treatment-resistant depression). Use this whenever the user asks for a "ketamine playlist", "infusion playlist", to "build my ketamine music", or references their ketamine/infusion sessions and wants music. Uses ytmusicapi to search real tracks and create an unlisted playlist on YouTube Music, following a fixed 50-minute, 3-phase protocol (Build / Peak / Wind-down) and never reusing tracks from prior session playlists.
---

Build a 50-minute YouTube Music playlist (40 min active infusion + 10 min comedown) for a
ketamine infusion session, following the fixed 3-phase protocol in
`references/phase-template.md`: **Build** (0:00-35:00, intensifying ambient/downtempo),
**Peak** (35:00-45:00, immersive melodic electronic anchored on Max Cooper), **Wind-down**
(45:00-50:00+, gentle emergent closers). Read that file and `references/curation-notes.md`
before curating tracks — they hold the full character description per phase and notes from
prior sessions.

All scripts run via the dedicated venv's python:
`~/.local/share/ketamine-playlist/venv/bin/python3 scripts/<script>.py`. If that venv doesn't
exist yet, create it and install `requirements.txt` first (see
`references/ytmusicapi-guide.md`).

## Workflow

1. **Preflight.** Ensure the venv exists and `ytmusicapi` is installed. Run
   `scripts/setup_auth.py` — it verifies existing auth with a live search, or walks the user
   through capturing browser headers if none exists yet or the existing ones are stale.

2. **Seed the exclude-list (first run only).** If
   `~/.local/share/ketamine-playlist/exclude-playlists.json` doesn't exist yet, run
   `scripts/build_playlist.py --list-playlists`, show the user their library playlists, and ask
   which ones (if any) are prior ketamine-session playlists whose tracks should never be
   reused. Add the chosen ones with `scripts/build_playlist.py --add-exclude ID [ID ...]`. Skip
   this step on later runs — the exclude-list persists.

3. **Curate.** Propose candidate tracks for each phase (as "Artist - Title" strings), honoring
   the phase-template's character descriptions, `curation-notes.md`, and the diversity rule
   (prefer non-consecutive artists; cap ~2-3 tracks per artist per playlist, except the
   Max-Cooper-heavy Peak). Don't worry about resolving exact runtimes by hand — the next step
   checks that mechanically. Write the plan to a JSON file, e.g. `/tmp/ktm-plan.json`:

   ```json
   {
     "title": "Ketamine Session — <today's date>",
     "phases": [
       {"name": "Build", "tracks": ["Artist - Title", "..."]},
       {"name": "Peak", "tracks": ["Max Cooper - ...", "..."]},
       {"name": "Wind-down", "tracks": ["Artist - Title", "..."]}
     ]
   }
   ```

4. **Dry-run.** Run `scripts/build_playlist.py --plan /tmp/ktm-plan.json --dry-run`. It
   resolves every track via ytmusicapi search, drops any already used in an excluded playlist
   or not found (reporting both), flags diversity-rule and phase-timing issues, and prints a
   full timeline with cumulative time. Nothing is created yet.

5. **Iterate.** If there are blocking issues (not-found tracks, already-used tracks, or total
   under 50:00) or the timeline doesn't look right, revise the plan file (swap tracks, add
   more to a short phase) and re-run step 4. Show the user the timeline before creating
   anything.

6. **Create.** Once the user approves, run the same command without `--dry-run`. This creates
   an **unlisted** playlist titled with the date, adds the resolved tracks in phase order, and
   records the new playlist's ID in the exclude-list so its tracks aren't reused next time.
   Report the playlist URL and final timeline back to the user.

7. **Optional follow-up.** If the user mentions standout tracks or things that didn't work
   after a session, append a short note to `references/curation-notes.md` for next time.

For full ytmusicapi call details (auth setup, search/playlist API shapes), see
`references/ytmusicapi-guide.md`.
