# ytmusicapi reference (as used by this skill)

Docs: https://ytmusicapi.readthedocs.io/ · Repo: https://github.com/sigma67/ytmusicapi

## Install

Homebrew Python (3.11 on this machine) enforces PEP 668 (externally-managed environment), so
install into a dedicated venv rather than system Python:

```bash
python3 -m venv ~/.local/share/yt-music-playlist/venv
~/.local/share/yt-music-playlist/venv/bin/pip install -r requirements.txt
```

Run every script through that venv's python, e.g.:

```bash
~/.local/share/yt-music-playlist/venv/bin/python3 scripts/build_playlist.py --dry-run --plan plan.json
```

This venv and the auth/lyrics-cache below are shared by every skill built on top of this one
(auth is account-level, not specific to any one playlist protocol). No-reuse tracking is opt-in
and per-consumer when used; see `--exclude-dir` below.

## Auth (browser-headers method)

`ytmusicapi.setup(filepath=...)` (wrapped by `scripts/setup_auth.py`) prompts the user to
paste request headers copied from music.youtube.com in the browser and writes them to a JSON
file. Steps (also printed by `setup_auth.py`):

1. Open music.youtube.com, logged in.
2. DevTools -> Network tab -> filter for `/browse` requests.
3. Click a POST request with status 200.
4. Copy the request headers (Firefox: right-click -> Copy -> Copy Request Headers; Chrome/Edge:
   "Copy as fetch (Node.js)" and extract Accept, Authorization, Content-Type, X-Goog-AuthUser,
   x-origin, Cookie).
5. Paste when prompted.

The resulting file (`~/.local/share/yt-music-playlist/browser.json`) contains session cookies
— never commit it. It can go stale (session expiry); `setup_auth.py` verifies it with a live
search call and offers `--force` to redo the capture.

```python
from ytmusicapi import YTMusic
yt = YTMusic("~/.local/share/yt-music-playlist/browser.json")
```

## Calls this skill uses

- `search(query, filter="songs", limit=N)` -> list of dicts with `videoId`, `title`,
  `artists` (list of `{name, id}`), `album`, `duration` (str), `duration_seconds` (int).
  Falls back to `filter="videos"` if a song search comes up empty (some tracks are only
  catalogued as videos).
- `create_playlist(title, description, privacy_status="UNLISTED", video_ids=None)` -> returns
  the new `playlistId`. `privacy_status` is one of `PUBLIC` / `PRIVATE` / `UNLISTED`.
- `add_playlist_items(playlistId, videoIds, duplicates=True)` -> adds items in the given list
  order, so phase ordering (Build -> Peak -> Wind-down) is preserved in the playlist. **Can
  transiently return HTTP 409 Conflict immediately after `create_playlist`** — confirmed by
  live testing, not documented behavior. `build_playlist.py`'s `_add_items_with_retry` retries
  up to 3 times with backoff; call through it rather than the raw API when adding items right
  after creating a playlist.
- `remove_playlist_items(playlistId, videos)` -> each item needs **both** `videoId` and
  `setVideoId`. `setVideoId` is only available from `get_playlist()` (search results don't have
  it) — fetch the live playlist first if you need to remove specific items.
- **No reorder primitive.** There is no API call to move an item to a specific position.
  `--sync`'s approach (remove everything, then re-add in the desired order) is the reliable way
  to get an exact track order, at the cost of transiently emptying the playlist mid-operation.
- `get_playlist(playlistId, limit=None)` -> dict including a `tracks` list (each with
  `videoId`, `setVideoId`, `title`, `artists`, `duration_seconds`); used both to fetch the live
  contents of excluded playlists and, via `--show`/`--sync`, to edit a live playlist.
- `get_library_playlists(limit=None)` -> list of `{playlistId, title, count, ...}`; used to
  let the user pick which existing playlists to exclude from, on first run.
- `delete_playlist(playlistId)` -> permanently deletes a playlist. Not used by any script
  command (no destructive playlist-deletion feature exists here); only ever called ad hoc to
  clean up a throwaway test playlist during development.

## Exclude-lists (`--exclude-dir`, opt-in)

By default `build_playlist.py` has no memory of past playlists — every `--plan`/`--sync` run is
independent, and nothing is checked against or added to any exclude-list. No-reuse tracking
(which playlists' and individual tracks' videoIds should never be added again) only activates
when an exclude-dir is available, and is per-consumer, not global: each skill built on this
engine (or an ad hoc request that wants it) picks its own dir, which holds two files:
`exclude-playlists.json` (`{"id", "name"}` entries, managed by
`--add-exclude`/`--remove-exclude`/`--finalize`) and `exclude-tracks.json` (`{"videoId", "name"}`
entries, managed by `--add-exclude-track`/`--list-exclude-tracks`).
`ytm.get_all_excluded_video_ids(client, exclude_dir)` unions both, fetching each excluded
playlist's current contents live. Without an exclude-dir, `--plan`/`--sync` skip this check
entirely (empty exclude set) and `--finalize`/`--add-exclude`/etc. are simply unavailable
(they error if invoked without one, since there'd be nowhere to write).

The exclude-dir can come from either **`--exclude-dir DIR`** on the command line, or a
**`--protocol`'s own `"exclude_dir"`** field (see below) — the CLI flag wins if both are given.
Baking `exclude_dir` into a protocol lets a consuming skill (e.g. ketamine-infusion-playlist)
always get no-reuse tracking just by passing `--protocol`, without repeating `--exclude-dir` on
every invocation.

## Protocol config (`--protocol`)

`build_playlist.py` takes an optional `--protocol PATH` pointing at a JSON config that
supplies all the policy a specific playlist-building skill wants layered on top of this
generic engine: segment names/targets, tolerance, artist-diversity rules, vocal-detection
mode, and a total-length boundary. Without `--protocol`, the plan is built unconstrained (any
phase names, no timing/diversity checks, vocal detection off).

```json
{
  "segments": [
    {"name": "Build", "target_seconds": 2100},
    {"name": "Peak", "target_seconds": 600, "diversity_exempt": true},
    {"name": "Wind-down", "target_seconds": 300, "count_to_boundary_only": true}
  ],
  "total_target_seconds": 3000,
  "phase_tolerance_seconds": 90,
  "diversity": {"max_tracks_per_artist": 3, "no_consecutive_same_artist": true},
  "vocal_policy": {"mode": "block", "exception_after_seconds": 2820, "exception_slot": "last"},
  "title_prefix": "My Playlist",
  "privacy_status": "UNLISTED",
  "description": "Generated by <skill> using yt-music-playlist.",
  "exclude_dir": "~/.local/share/my-skill",
  "audio_policy": {"voice_flag_frac": 0.25, "max_loudness_jump_lu": 10}
}
```

- **`segments`**: if given, a plan's phase names must match one of these (otherwise flagged as
  unknown). `target_seconds` here is the default per-segment target; a plan entry's own
  `target_seconds` overrides it. `diversity_exempt` relaxes the diversity rules (below) just for
  that segment — e.g. a Peak phase intentionally heavy on one artist. `count_to_boundary_only`
  measures that segment's length only up to `total_target_seconds` and flags a shortfall only,
  never an overflow — for a segment whose tail past the boundary doesn't matter.
- **`total_target_seconds`**: doubles as (a) the grand-total minimum for the whole playlist and
  (b) the hard boundary — no track may *start* at/after this mark. Omit for no such constraint.
- **`phase_tolerance_seconds`**: +/- allowance before a segment's duration mismatch is flagged
  (informational unless a segment has no target, in which case no check runs at all).
- **`diversity`**: omit entirely to skip artist-diversity checks. `max_tracks_per_artist` caps
  how many times one artist may appear (omit for no cap); `no_consecutive_same_artist` flags
  back-to-back tracks by the same artist.
- **`vocal_policy.mode`**: `"off"` (default — skip all vocal work), `"flag"` (report vocal
  signals as advisory only, never blocking), or `"block"` (confirmed lyrics is a hard block).
  `exception_after_seconds` + `exception_slot: "last"` allow exactly one vocal track — the
  playlist's final track — if it starts at/after that mark (e.g. a deliberate vocal closer). A
  plan's top-level `"vocal_ok": ["Artist - Title", ...]` list manually clears a query the
  heuristics flag as a verified false positive, regardless of mode.
- **`title_prefix` / `privacy_status` / `description`**: defaults used when creating a playlist,
  if the plan doesn't set its own `"title"`.
- **`exclude_dir`**: opts this protocol's consumer into no-reuse tracking (see "Exclude-lists"
  above) without needing `--exclude-dir` on the command line. `~` and env vars are expanded; a
  path that's still relative afterward is resolved against the protocol file's own directory
  (not the current working directory), so a protocol can portably point at a sibling path.
  `--exclude-dir` on the command line overrides this if both are present. Omit for no default
  (no-reuse tracking off unless `--exclude-dir` is passed explicitly).
- **`audio_policy`**: opts into audio-content analysis (see "Audio analysis" below). Omit it
  entirely, and no audio work happens. A segment entry may also carry `"arc": "rising"` or
  `"falling"` for the intensity-arc check.

## Vocal/lyrics detection mechanics

- `get_watch_playlist(videoId=...)` returns a dict that may include a `"lyrics"` key holding a
  browseId; `get_lyrics(browseId)` resolves that to `{"lyrics": "...", ...}` if lyrics text
  exists.
- **This is not fully reliable, confirmed by live testing:** the `lyrics` browseId can be
  present on purely instrumental tracks (false positive on presence alone), and `get_lyrics`
  has returned `None` even for a track with confirmed audible vocals (false negative). Do not
  treat browseId presence, or `get_lyrics` success alone, as a reliable signal either way.
- `ytm.check_vocals(client, video_id)` treats **actual returned lyrics text** as the only
  positive signal (`True`); a missing browseId or empty lyrics is `False`; a lookup exception is
  `None` (inconclusive, never blocking). Results are cached to `lyrics-cache.json` (only
  definitive `True`/`False`, never `None`, so a failed lookup is retried next run).
- Because the lyrics signal alone has false negatives, `build_playlist.py` ORs it with
  `ytm.is_likely_vocal_title()` (title contains `feat.`/`ft.`/`featuring`, or the track only
  resolved via the `"videos"` search filter rather than `"songs"`) as an advisory-level flag
  alongside whatever `vocal_policy.mode` dictates for the hard signal.

## Audio analysis (optional)

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
- Without these packages installed, `analyze_tracks.py` exits with a one-line reason and
  `build_playlist.py` adds a single "audio analysis unavailable" note. Nothing else changes.

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
- A jump is the next track's `loud_start` minus the previous track's `loud_end`, both
  normalized.

**`audio_policy` keys** (defaults from `build_playlist.AUDIO_POLICY_DEFAULTS`; `null` turns a
check off):
- `voice_flag_frac` (0.25): flag any track with at least this share of voice frames.
  - It's advisory only: cleared per track via the plan's `vocal_ok`, and skipped for the
    `vocal_policy` exception slot.
  - Confirmed lyrics text stays under `vocal_policy`'s block/flag rules.
- `max_loudness_jump_lu` (null), `max_arousal_jump` (null), `max_tempo_ratio` (null): warn on
  adjacent-track jumps above these. Tempo is compared after folding out half and double time,
  and only when both `bpm_conf` >= `min_bpm_confidence` (1.5).
- `arc_metric` (`"arousal"`) and `arc_tolerance` (0.5): check segments marked with an `arc`.
  - `rising` warns on any step down larger than the tolerance, and when the segment doesn't
    end higher than it starts.
  - `falling` is the mirror image.
- `playback_normalization_lufs` (-14): see above.

Every audio issue is **advisory**, never blocking, and so is an "audio unanalyzed" track
(e.g. a failed download). `--no-audio-check` skips the whole thing for fast iteration.

## Notes

- Track resolution is fuzzy — always sanity-check a search result's title/artist against the
  intended query before treating it as a match. `ytm.resolve_track()` takes only the top result;
  when a query might be ambiguous (edits/remixes/features sharing a title with the plain track —
  this has happened in practice, e.g. "Max Cooper - Repetition" top-matching "Repetition
  (Edit)"), use `scripts/search_tracks.py -n 5 "Artist - Title"` (backed by
  `ytm.resolve_candidates()`) to see multiple candidates and pick deliberately, or narrow the
  query string.
- `duration_seconds` is the source of truth for timeline math, not the human-readable `duration`.
