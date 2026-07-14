# Curation notes

Living notes on what's worked, to season track selection alongside `phase-template.md`.
Append to this file over time — e.g. after a session, note standout tracks or artists to
avoid repeating too heavily.

## Peak (35:00-45:00)
- Anchor artist: **Max Cooper** (melodic, immersive, builds without becoming jarring).
- Other artists in a similar register are welcome for variety within the cap.

## Build (0:00-35:00)
- Ambient / downtempo, intensifying gradually across the full 35 minutes.
- Avoid looping the same mood the whole phase — vary texture while keeping the overall arc calm-to-rising.

## Wind-down (45:00-50:00+)
- Gentle, emergent, a felt sense of "return."
- 1-3 tracks is usually enough; don't overfill past the target just to add variety.
- The final track may carry vocals only if it starts at/after 47:00 — everything else in the
  playlist must be fully instrumental. See "Instrumental-only" below.

## Instrumental-only (hard rule)
- No lyrics anywhere in the playlist, except possibly a single closing track starting at/after
  47:00. `build_playlist.py` enforces this automatically (confirmed lyrics text = hard block;
  `feat.`/`ft.`/`featuring` in the title = flag) — see `references/ytmusicapi-guide.md` for how
  the check works and its known false-negative risk.
- If a query's version is ambiguous (an edit/remix/feature shares a title with the plain track),
  disambiguate with `scripts/search_tracks.py -n 5 "Artist - Title"` before adding it to a plan
  rather than trusting the top search hit.

## Do-not-use
- Permanently disliked or ill-fitting tracks are tracked in
  `~/.local/share/ketamine-playlist/exclude-tracks.json`, managed via
  `scripts/build_playlist.py --add-exclude-track` / `--list-exclude-tracks` (checked
  automatically by every plan/dry-run) — don't duplicate that list here in prose.

## General preferences
- (add tempo preferences or other qualitative notes here as they come up)
