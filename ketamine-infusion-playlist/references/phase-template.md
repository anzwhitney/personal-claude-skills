# Phase template — 50-minute protocol

Fixed protocol: 40 min active infusion + 10 min comedown = 50 min total. Times are
cumulative from infusion start. Mirrored in code as `ytm.PHASES`.

General rules:
- Gradual intensification into the Peak, then soft emergence — no abrupt dynamic jumps between adjacent tracks.
- **Instrumental only:** every track must have no lyrics at all, except possibly a single final
  track that *starts* at/after 47:00 (a deliberate vocal closer). Enforced mechanically by the
  shared `yt-music-playlist` skill's `build_playlist.py` (combined lyrics lookup + title
  heuristic), driven by this skill's `protocol.json` (`vocal_policy`) — see
  `yt-music-playlist`'s `references/vocal-detection.md` for how the check works.
- **Timing:** the playlist may run well past 50:00 — content after that point doesn't matter,
  since the supervising clinician fades the music out around then regardless of what's queued.
  The only hard rule is that no track may *start* at/after 50:00. Wind-down's length is measured
  only up to the 50:00 boundary; overflow past it is never penalized. (`protocol.json`:
  `total_target_seconds` / Wind-down's `count_to_boundary_only`.)
- **Artist diversity (whole playlist):** prefer consecutive tracks by different artists, and
  cap each artist at **2-3 tracks per playlist** unless the user says otherwise. Exception:
  the Peak phase is intentionally heavy on one immersive artist (Max Cooper by default) —
  both the consecutive-artist and per-artist-cap rules are relaxed there. (`protocol.json`:
  `diversity` / Peak's `diversity_exempt`.)

| # | Phase | Window | ~Len | Character |
|---|-------|--------|------|-----------|
| 1 | **Build** | 0:00-35:00 | ~35 min | Gradually intensifying ambient / downtempo. Calm, textural foundations early; density and energy rising steadily toward the peak. The long tail of the session. |
| 2 | **Peak** | 35:00-45:00 | ~10 min | The most intense point — immersive melodic electronic (Max Cooper or similar). Rhythmic/building is welcome here (not beatless). Spans the end of the active infusion into early comedown. |
| 3 | **Wind-down** | 45:00-50:00+ | ~5 min+ (measured only to 50:00; may overflow past it) | 1-3 gentle closing tracks for soft emergence. The last track may carry vocals only if it starts at/after 47:00. |

## Curation notes from prior sessions
- **Peak anchor:** Max Cooper, and similarly immersive melodic-electronic artists.
- **Build** leans intensifying ambient/downtempo — this is the long tail of the session, so
  vary texture across it rather than looping one mood for 35 minutes.
- **Wind-down** favors gentle, emergent closers — something that feels like a return.
- Timing precision matters to the user; keep phase windows tight (see
  `phase_tolerance_seconds` in `protocol.json` for the automated tolerance check).

See `curation-notes.md` for a growing list of specific artists/tracks that have worked well,
and any do-not-use notes.
