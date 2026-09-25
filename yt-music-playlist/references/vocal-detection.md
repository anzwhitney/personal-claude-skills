# Vocal/lyrics detection mechanics

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
