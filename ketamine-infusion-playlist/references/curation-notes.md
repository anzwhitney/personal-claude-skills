# Curation notes

Living notes on what's worked, to season track selection alongside `phase-template.md`.
Append to this file over time — e.g. after a session, note standout tracks or artists to
avoid repeating too heavily.

## Reference sessions (pre-skill, hand-curated)

The user's own best examples, and the calibration source for `protocol.json`'s
`audio_policy`:

- **"[OG] Ketamine - revised"** (`PL9yl9AZo1F71EQOSQuRqVfVV0ROQw3Mes`)
- **"Anz Ketamine - Thunderstorm"** (`PL9yl9AZo1F72hyKFxNJJNAGJ7eC8EH7GX`)
- **"Anz Ketamine - Water"** (`PL9yl9AZo1F73cSXaYVoE8d6loKElzvugh`)

Their tracks are already in the audio cache. `analyze_tracks.py --playlist ID` shows them
instantly, and any of their tracks makes a good `--similar-to` reference. What they share,
as measured on 2026-09-24:

- **Build settles, then climbs.** Arousal starts ~4.2-4.4, dips to ~3.5-3.8 over tracks 2-5,
  then climbs to ~5.5-6.3 by 30-35 min. Rank trend +0.63 / +0.69 / +0.82. "Relaxed" falls in
  step. Loudness does *not* follow the build; quiet field-recording and piano tracks sit
  between louder ones.
- **The texture palette** is field recordings / nature sound (rain, water, storms), Yosi
  Horikawa, Kishi Bashi, Max Cooper's ambient side, and post-rock or acoustic interludes.
  Max Cooper usually arrives in late Build (Wasp, Autumn Haze, Order from Chaos).
- **Peak in practice is not the loudest or most energetic stretch.** Arousal there often
  steps *down* from late Build (e.g. Wasp 6.3 -> Small Giraffes 4.0). That's why
  `protocol.json` sets no arc on Peak.
- **Peak's goal is *immersive*, not intense, and no measured feature captures immersion.**
  Tested 2026-09-24 on the reference sessions plus the Beach session:
  - Similarity to Max Cooper's style profile doesn't mark Peak picks. Build tracks scored
    *more* Max-Cooper-like (0.76) than non-Max-Cooper Peak picks (0.53), and "Small
    Giraffes" / "Your Hand in Mine" scored near zero.
  - Nothing else separates Peak from Build either: duration, loudness range, swell, arousal,
    mood, onset density.

  So choose Peak tracks by ear, with "Max Cooper or similar" as the anchor. Use
  `analyze_tracks.py --similar-to` against tracks the user has called immersive only to
  *find candidates*, never as a score.
- **Closers:** one track, anywhere from calm (CSNY "Helplessly Hoping", the vocal exception)
  to bright (Fakear "Water Lullaby", arousal 6.0).
- **Transitions:** a track rarely opens more than ~3 LU above the previous track's level
  (max +9); arousal changes are usually under ~0.9 between neighbours.

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
  47:00. Enforced automatically by the shared `yt-music-playlist` skill's `build_playlist.py`,
  driven by this skill's `protocol.json` `vocal_policy` (confirmed lyrics text = hard block;
  `feat.`/`ft.`/`featuring` in the title = flag) — see that skill's
  `references/vocal-detection.md` for how the check works and its known false-negative risk.
- If a query's version is ambiguous (an edit/remix/feature shares a title with the plain track),
  disambiguate with the shared skill's `scripts/search_tracks.py -n 5 "Artist - Title"` before
  adding it to a plan rather than trusting the top search hit.

## Do-not-use
- Permanently disliked or ill-fitting tracks are tracked in
  `~/.local/share/ketamine-playlist/exclude-tracks.json` (this skill's `--exclude-dir`), managed
  via the shared skill's `build_playlist.py --exclude-dir ~/.local/share/ketamine-playlist
  --add-exclude-track` / `--list-exclude-tracks` (checked automatically by every plan/dry-run) —
  don't duplicate that list here in prose.

## General preferences
- (add tempo preferences or other qualitative notes here as they come up)
