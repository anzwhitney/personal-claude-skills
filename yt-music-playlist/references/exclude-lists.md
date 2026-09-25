# Exclude-lists (`--exclude-dir`, opt-in)

By default `build_playlist.py` has no memory of past playlists — every `--plan`/`--sync` run is
independent, and nothing is checked against or added to any exclude-list. No-reuse tracking
(which playlists' and individual tracks' videoIds should never be added again) only activates
when an exclude-dir is available, and is per-consumer, not global: each skill built on this
engine (or an ad hoc request that wants it) picks its own dir, which holds two files:
`exclude-playlists.json` (`{"id", "name"}` entries, managed by
`--add-exclude`/`--remove-exclude`/`--finalize`) and `exclude-tracks.json` (`{"videoId", "name",
"duration_seconds"}` entries, managed by `--add-exclude-track`/`--list-exclude-tracks`).
`ytm.get_used_tracks(client, exclude_dir)` unions both, fetching each excluded playlist's
current contents live.

**Matching is by recording, not just videoId.** The same recording often has several videoIds
(an album track and its single, a re-upload), so a plan track is also "already used" when
`ytm.track_key()` matches a used track and the lengths agree within 5 s. The key is the first
artist, the base title and its version tags, all lowercased with accents and punctuation
removed:
- Release labels are ignored: *Remastered [year]*, *Album Version*, *Original Mix*,
  *Official Audio/Video*.
- Any other qualifier is a different track: remix, rework, edit, extended, live, feat., 3D and
  so on. So "Origins (Extended)" is not "Origins".
- The same key at a different length gives an advisory "possible other version of a used
  track", not a block, since it may be a different cut.
- Entries without a stored length (older exclude-track entries) match any length.
- The dry-run names which used track and playlist matched. Two entries in one plan that are
  the same recording are flagged as `DUPLICATE`.
- A re-titled reissue still slips through: catching it would need audio fingerprinting. Without an exclude-dir, `--plan`/`--sync` skip this check
entirely (empty exclude set) and `--finalize`/`--add-exclude`/etc. are simply unavailable
(they error if invoked without one, since there'd be nowhere to write).

The exclude-dir can come from either **`--exclude-dir DIR`** on the command line, or a
**`--protocol`'s own `"exclude_dir"`** field (see `protocol-config.md`) — the CLI flag wins if
both are given. Baking `exclude_dir` into a protocol lets a consuming skill (e.g.
ketamine-infusion-playlist) always get no-reuse tracking just by passing `--protocol`, without
repeating `--exclude-dir` on every invocation.
