# Audio-content analysis for yt-music-playlist

Status: **proposed** (2026-09-24). Companion: `plans/cloud-sessions.md`, which has to run this
feature in cloud sessions later.

## Context

Today curation is blind to the audio. The engine only checks metadata: duration, artist and
lyrics text. So it can't tell whether Build actually intensifies, whether a transition jumps,
whether a track *feels* right for a phase, or whether a "lyric-free" track has wordless or
chopped vocals. The goal is audio-derived features that (a) Claude can consult while curating
and (b) the dry-run checks mechanically, with the thresholds set in `--protocol`.

## Decisions (made with the user)

- **Uses:** all four. Energy/intensity arc per segment, smooth transitions, audio-based vocal
  detection, and mood/texture matching (including "sounds like X").
- **No third-party MCP server.** None of the evaluated servers fit:
  - hugohow/mcp-music-analysis: pins pytubefix 8.12.2 and fastmcp 0.4.1, last commit Aug 2025.
    Returns raw arrays (MFCCs, onsets). No loudness, vocal or mood data.
  - audio-analyzer-rs: solid signal-processing numbers but no vocal or mood detection, and a
    second implementation would disagree with the engine's numbers.
  - audio-sonic-mcp: vocal presence and CLAP mood tags, but a ~4GB torch/Demucs stack. Too
    heavy, especially for cloud.
  - music21: symbolic scores only, so not applicable.

  Instead, build one in-skill analysis module on **Essentia**. It provides the signal-processing
  features plus small TF models: voice/instrumental, mood, arousal/valence, and embeddings for
  similarity.
- **Interface:** a CLI script (`analyze_tracks.py`) called through Bash, matching the
  `search_tracks.py` pattern. No MCP registration, and it behaves the same in cloud.
- **Integration:** the CLI gives Claude advisory data during curation, **and** the dry-run adds
  audio columns and warnings to the timeline.
- **Vocal rule:** any audible voice (wordless, chopped samples, choir) → **flag** (a warning,
  cleared per track via `vocal_ok`). Confirmed lyrics text stays a hard **block**, as today.
- **Audio source:** yt-dlp by `videoId`, i.e. the exact version going into the playlist.

## Spike results (2026-09-24, this Mac)

- yt-dlp 2026.08.19 fetched `bestaudio[ext=m4a]` from `music.youtube.com/watch?v=ID` with no
  cookies and no JS runtime. 4–8MB per track.
- `essentia-tensorflow==2.1b6.dev1389` installs on py3.11 macOS arm64. It's the last release
  with cp39–cp313 wheels on both macOS arm64 and linux x86_64; the latest release (dev1438)
  is cp314-only, so **pin it**. Wheel ~140MB, models ~25MB total.
- **Speed:** 10–20s per 4–8 min track for everything (effnet + musicnn + loudness + rhythm +
  key).
- **Results:**

  | Track | Voice frames | Relaxed | Arousal (1–9) | Loudness thirds (LUFS) |
  |---|---|---|---|---|
  | Max Cooper – Order From Chaos | 3% | 0.84 | 4.9 | −22 → −11 → −11 |
  | Nils Frahm – Says | 1% | 0.95 | 3.9 | −29 → −23 → −11 |
  | Bonobo – Kerala | **40%** | — | — | — |

  "Says" shows its build clearly. Kerala's 40% correctly catches its vocal chops, which the
  lyrics lookup misses. Mood heads are coarse (e.g. Max Cooper scored 0.84 "danceable"), so
  treat them as relative signals, not labels.

## Design

All new code lives in `yt-music-playlist/`. Everything is optional: the base skill works
without the audio dependencies installed.

### 1. Dependencies: `requirements-audio.txt` (new)

- `essentia-tensorflow==2.1b6.dev1389`, pinned for the wheel-availability reason above.
- `yt-dlp>=2026.8`. **Unpinned upper bound** on purpose: YouTube breaks old yt-dlp versions,
  so preflight runs `pip install -U yt-dlp` when a download fails.
- Kept separate from `requirements.txt` so the base skill stays light.
- Install into the existing shared venv (`~/.local/share/yt-music-playlist/venv`, py3.11).

### 2. Library: `scripts/audio.py` (new)

- **`ensure_models()`** downloads a pinned list of model files, each with URL + sha256, from
  `essentia.upf.edu/models/` into `STATE_DIR/models/`:
  - `discogs-effnet-bs64-1`, the embedding backbone;
  - heads on effnet: `voice_instrumental`, `mood_relaxed`, `mood_sad`, `mood_aggressive`,
    `danceability`;
  - `msd-musicnn-1` + `emomusic-msd-musicnn-2` for arousal/valence.
- **`fetch_audio(video_id)`** uses yt-dlp's Python API: `bestaudio[ext=m4a]/bestaudio` into a
  temp dir under `STATE_DIR/audio-tmp/`. The file is **deleted right after analysis**. Only
  derived features are kept, never audio.
- **`analyze(video_id)`** returns a compact feature dict, cached by `videoId`:
  - `voice_frac` (share of effnet frames with voice > 0.5), `voice_mean`;
  - `relaxed`, `sad`, `aggressive`, `danceable` (mean probabilities);
  - `arousal`, `valence` (1–9);
  - `lufs` (integrated), `lra`, `loud_start` / `loud_end` (short-term LUFS over the first and
    last 20s), `loud_contour` (10-point short-term LUFS);
  - `bpm`, `bpm_conf`, `key`, `scale`, `key_strength`, `centroid` (brightness);
  - `source` (`"full"`, with `"preview"` reserved for the cloud fallback), `analyzer_version`.
- **Caches:** designed so the cloud plan can move them into the repo with just a path change.
  - `STATE_DIR/audio-features.json` is sorted-key JSON, one track per line, so it diffs
    cleanly.
  - The 1280-d mean effnet embedding goes in a separate `STATE_DIR/audio-embeddings.json`
    (float16, base64) to keep the features file readable.
  - Bumping `ANALYZER_VERSION` invalidates old entries.
- **Failures:** a failed download or decode returns `None` with a reason. The caller reports
  "unanalyzed" and never blocks.

### 3. CLI: `scripts/analyze_tracks.py` (new)

- **Input:** `"Artist - Title"` queries, bare videoIds, `--plan plan.json`, or `--playlist ID`.
  Queries resolve through `ytm.resolve_track`. Tracks are analyzed sequentially with the models
  loaded once, so batching amortizes the ~5s load.
- **Default output:** a compact one-line-per-track table (voice%, arousal/valence, relaxed,
  LUFS start→end, bpm, key) that's cheap in context. `--json` gives the full dicts.
- **`--similar-to "Artist - Title"`** ranks the other given tracks by embedding cosine
  similarity. This supports "find Build tracks that feel like X" and matching a reference
  track's texture.
- **`--transitions`** (with `--plan`) prints each adjacent pair's loudness jump
  (end→start LU), arousal delta, tempo ratio and key distance, so Claude can reorder before a
  dry-run.

### 4. Engine: `build_playlist.py`

- **New optional protocol block `audio_policy`.** Absent means no audio work, so the
  unconstrained or protocol-less path is unchanged. `--no-audio-check` skips it for fast
  iteration, like `--no-lyrics-check`. With the block present, dry-run, create and sync analyze
  every resolved track (cached) and add columns to the timeline: voice%, arousal, LUFS s→e,
  bpm, key.
- **Vocal:** `voice_frac >= audio_policy.voice_flag_frac` → a **flag**. It reuses
  `vocal_policy`'s exception slot and `vocal_ok` clearing. The lyrics-text block is unchanged.
- **Transitions:** warn when |`loud_end`(n) − `loud_start`(n+1)| > `max_loudness_jump_lu`, when
  |Δarousal| > `max_arousal_jump`, or when the tempo ratio (after half/double folding) is outside
  `max_tempo_ratio`. Key distance is informational only. Any threshold set to `null` is off.
- **Arc:** per segment, `"arc": "rising" | "falling" | "flat" | null` in the protocol's segment
  entry. Checks the arousal (and integrated-loudness) trend across the segment's tracks via
  rank correlation plus a count of reversals larger than `arc_tolerance`. Violations are
  **warnings, never blocks**.
- **Unanalyzed tracks:** listed as an informational issue. The check never fails the run
  because of them.

### 5. ketamine-infusion-playlist

- **`protocol.json`:** add `audio_policy` with arcs Build `rising`, Peak `null` (or `flat`),
  Wind-down `falling`. The thresholds come from the calibration step below, not guesses.
- **`SKILL.md` curation step:**
  - audition candidates with `analyze_tracks.py` (especially voice% and arousal);
  - use `--similar-to` against known-good tracks from `curation-notes.md`;
  - run `--transitions` before the dry-run.
- **`curation-notes.md`:** record reference tracks per phase for similarity matching.

### 6. Calibration against prior sessions (part of implementation)

- Run `analyze_tracks.py --playlist` over the 11 playlists in the ketamine exclude-list
  (~150 tracks, ~40 min in the background, all cached afterward).
- Use the resulting distributions to set the initial `voice_flag_frac`, `max_loudness_jump_lu`,
  `max_arousal_jump` and `arc_tolerance`. The aim is that prior sessions you were happy with
  raise few or no warnings.
- Show you which prior tracks the voice detector would have flagged, to sanity-check its
  false-positive rate, before the thresholds get committed.

### 7. Docs

- `yt-music-playlist/SKILL.md`: an optional audio step in the workflow.
- `references/ytmusicapi-guide.md`: an "Audio analysis" section covering install, cache,
  `audio_policy` schema, caveats (coarse mood models, yt-dlp breakage, audio never retained)
  and model licensing (Essentia models are CC BY-NC-SA, fine for personal use).

## Commit sequence (branch `audio-analysis`)

1. `requirements-audio.txt` + `scripts/audio.py` (models, fetch, analyze, caches)
2. `scripts/analyze_tracks.py` CLI
3. `build_playlist.py` `audio_policy` integration + guide schema docs
4. Calibration run → ketamine `protocol.json` `audio_policy` + SKILL/curation docs
5. yt-music-playlist SKILL.md workflow update

## Verification

1. Fresh install of `requirements-audio.txt` into the shared venv. `ensure_models()` downloads
   and checksums the models.
2. `analyze_tracks.py "Max Cooper - Order From Chaos" "Bonobo - Kerala" "Nils Frahm - Says"`
   reproduces the spike numbers. The second run is instant (cache hit), and no audio is left in
   `audio-tmp/`.
3. `--similar-to` ranks two Max Cooper tracks above Kerala for a Max Cooper reference.
4. Dry-run the most recent ketamine plan with the protocol: audio columns appear, warnings are
   plausible, `--no-audio-check` and protocol-less runs behave exactly as before, and an
   uninstalled essentia produces a one-line "audio analysis unavailable" note, not a crash.
5. Calibration report reviewed with you before the thresholds are committed.
