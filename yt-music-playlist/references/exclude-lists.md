# Exclude-lists (`--exclude-dir`, opt-in)

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
**`--protocol`'s own `"exclude_dir"`** field (see `protocol-config.md`) — the CLI flag wins if
both are given. Baking `exclude_dir` into a protocol lets a consuming skill (e.g.
ketamine-infusion-playlist) always get no-reuse tracking just by passing `--protocol`, without
repeating `--exclude-dir` on every invocation.
