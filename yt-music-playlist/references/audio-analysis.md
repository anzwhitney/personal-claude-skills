# Audio analysis (optional)

`scripts/audio.py` derives features from how a track actually sounds:
- it downloads the track's audio by videoId with yt-dlp;
- it analyzes the audio with Essentia: signal measures plus small pretrained TF models from
  essentia.upf.edu (CC BY-NC-SA, so personal use only);
- it caches the features by videoId and deletes the audio. **Audio is never kept**, only
  derived numbers.

Two consumers use it:
- `scripts/analyze_tracks.py` for curation (see its `--help` for the column meanings);
- `build_playlist.py` when the protocol has an `audio_policy`.

**Install:**

```bash
~/.local/share/yt-music-playlist/venv/bin/pip install -r requirements-audio.txt
```

- `essentia-tensorflow` is pinned to `2.1b6.dev1389`. It's the last release with cp39-cp313
  wheels for both macOS arm64 and linux x86_64; newer builds are cp314-only.
- The `deno` extra of `yt-dlp` provides the JS runtime YouTube extraction now needs.
- If downloads start failing (YouTube changes often), first run
  `pip install -U "yt-dlp[default,deno]"`.
- Models (~27MB) download and checksum themselves on first use into
  `~/.local/share/yt-music-playlist/models/`.
- Without these packages installed, **cached tracks still work**: their features, the
  timeline columns and every `audio_policy` check. Only uncached tracks are left unanalyzed.
  `build_playlist.py` adds one "audio analysis unavailable" note giving the count.
  `analyze_tracks.py` prints the reason and exits 3. `--similar-to` needs the full install
  even for cached tracks, because it needs numpy.

**Cost:**
- ~15-30s per uncached track, since download + analysis runs on CPU;
- instant on cache hits (`audio-features.json`, with similarity vectors in
  `audio-embeddings.json`, both under `STATE_DIR`);
- YouTube intermittently answers a stream request with 403; `fetch_audio` retries with backoff.

**Features and what they're good for:**

| Feature | Meaning | Use |
|---|---|---|
| `voice_frac` | Share of ~2s frames with any voice, including wordless or sampled vocals | Catches what the lyrics lookup can't (e.g. Bonobo – Kerala ≈ 40%). Pure instrumentals measured 0–6%. |
| `arousal` / `valence` | Energy and positivity, 1–9 | `arousal` is the default intensity measure for arcs. |
| `relaxed` / `sad` / `aggressive` / `danceable` | Mean class probabilities | **Coarse**: compare tracks with each other, don't read them as labels. |
| `styles` | Top Discogs styles | E.g. `Electronic/Ambient`, `Classical/Neo-Classical`. |
| `lufs` / `lra` | Integrated loudness / loudness range | |
| `loud_start` / `loud_end` | 75th-percentile short-term LUFS over the edge 30s | Transition checks. |
| `loud_contour` | 10-point contour | The shape of the track. |
| `onset_rate` | Events per second | Textural density. |
| `bpm` / `bpm_conf` | Tempo, confidence below 1.5 = unreliable | Unreliable is typical for ambient; tempo checks skip those. |
| `key` / `scale` | Shown as a Camelot code | 1 step = harmonically adjacent. |

- **Similarity** (`--similar-to`) is cosine similarity of the 400-d Discogs style activations.
  Raw effnet embeddings rated nearly everything ~0.7 alike in testing.
- It measures sound, not artist: Max Cooper's ambient "Order From Chaos" sits nearest Jon
  Hopkins and Stars of the Lid, not his own techno.

**Transitions and playback normalization:**
- YouTube Music turns tracks louder than about -14 LUFS down to that level and never boosts
  quieter ones. Transition loudness is therefore computed on the normalized playback level
  (`playback_normalization_lufs`, null = raw).
- The transition measure is **loudness rise**: the next track's `loud_start` minus the
  previous track's overall (integrated) level, both normalized.
- The previous track's *overall* level is used, not its last seconds. After a fade-out, a
  normal start isn't jarring, and drops into a quiet intro are routine in hand-curated
  sessions. A track that opens clearly louder than what came before *is* jarring, so only
  rises are checked.

**`audio_policy` keys** (defaults from `build_playlist.AUDIO_POLICY_DEFAULTS`; `null` turns a
check off):
- `voice_flag_frac` (0.25): flag any track with at least this share of voice frames.
  - It's advisory only: cleared per track via the plan's `vocal_ok`, and skipped for the
    `vocal_policy` exception slot.
  - Confirmed lyrics text stays under `vocal_policy`'s block/flag rules.
- `max_loudness_rise_lu` (null), `max_arousal_jump` (null), `max_tempo_ratio` (null): warn on
  adjacent-track changes above these. Tempo is compared after folding out half and double time,
  and only when both `bpm_conf` >= `min_bpm_confidence` (1.5).
- `arc_metric` (`"arousal"`), `arc_tolerance` (1.0) and `arc_min_correlation` (0.3): check
  segments marked with an `arc`.
  - `rising` warns on any single step down larger than `arc_tolerance`.
  - It also warns when the segment's rank correlation with track order is below
    `arc_min_correlation`, i.e. the overall trend barely rises.
  - `falling` is the mirror image.
  - The trend test deliberately tolerates dips. Hand-curated Builds typically settle for a few
    tracks before climbing.
- `playback_normalization_lufs` (-14): see above.

Every audio issue is **advisory**, never blocking, and so is an "audio unanalyzed" track
(e.g. a failed download). `--no-audio-check` skips the whole thing for fast iteration.
