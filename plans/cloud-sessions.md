# Make the skills usable, and the generic one runnable, in cloud Claude Code sessions

Status: **proposed, not started**. Drafted 2026-08 in session d153f31a. The file was lost from
`~/.claude/plans/` and recovered from that transcript. Updated 2026-09-24 for audio analysis
(Part 4; see `plans/audio-analysis.md`).

## Context

Cloud Claude Code sessions (claude.ai/code, remote agents) discover skills only from a cloned
repo's **`.claude/skills/`** directory. They never see local `~/.claude/skills/`. Today this
repo keeps each skill as a **top-level directory**, and `install.sh` symlinks them into
`~/.claude/skills/`. So `.claude/skills/` doesn't exist and cloud finds zero skills.

The goal goes beyond discovery:

- the generic **`yt-music-playlist`** skill should actually *run* in cloud;
- **`ketamine-infusion-playlist`**'s no-reuse feature should stop depending on ephemeral local
  state. It becomes a committed list of prior YTM playlist links, resolved at runtime.

Auth moves to **OAuth**, which can refresh and works headless.

Decisions already made:

- Scope: restructure the repo and make `yt-music-playlist` cloud-runnable. Simplify ketamine
  no-reuse to a committed link list rather than durable external storage.
- Auth mechanism: **OAuth**, not browser headers.

`.gitignore` only ignores `.claude/worktrees`, so a committed `.claude/skills/` is safe.

Cloud mechanics (from the Claude Code docs, 2026-08):

- **Setup:** either a UI-only **Setup script**, which is skipped on cached environments, or a
  repo-committed `SessionStart` hook in `.claude/settings.json`, which runs every session.
- **Secrets:** plain `.env` lines in the environment dialog. There is **no secure secrets
  store**.
- **Network:** the default "Trusted" level won't reach YouTube, so it needs `Full` or a
  `Custom` allowlist.

---

## Part 1: Restructure for discoverability

**Move, don't symlink.** Symlinking the top-level dirs into `.claude/skills/` was rejected:
nobody has verified that cloud follows symlinks, and it creates two sources of truth. Instead,
make `.claude/skills/<name>` the real home and flip `install.sh` to symlink *out* to
`~/.claude/skills/`.

1. `git mv ketamine-infusion-playlist .claude/skills/ketamine-infusion-playlist` and
   `git mv yt-music-playlist .claude/skills/yt-music-playlist`. `claude-config/` stays at the
   root.
2. `install.sh`:
   - keep the `claude-config/*` links;
   - change the skill loop to iterate `"$REPO_DIR"/.claude/skills/*/`;
   - drop the now-moot `claude-config` skip.

   The idempotent `link()` relinks stale `~/.claude/skills/*` symlinks on re-run.
3. `README.md`:
   - update the Layout diagram, the project-scope symlink example, and "Adding a new skill"
     step 1;
   - note that cloud sessions auto-load from `.claude/skills/` once pushed.

## Part 2: Make `yt-music-playlist` cloud-runnable

**A. Bootstrap the venv.** Add a committed, idempotent `scripts/cloud-bootstrap.sh` that:

- creates `~/.local/share/yt-music-playlist/venv` if it's missing;
- runs `pip install -r requirements.txt`;
- writes the OAuth file (see B).

Wire it up with a **`SessionStart` hook** (matcher `startup|resume`) in a new repo-root
`.claude/settings.json`. Keeping the fixed venv path keeps `PY=...` valid everywhere.

**B. OAuth auth.**

- `ytm.py`: add `OAUTH_FILE = STATE_DIR / "oauth.json"`. `get_client()` uses
  `YTMusic(str(OAUTH_FILE), oauth_credentials=OAuthCredentials(client_id, client_secret))`,
  with the credentials from `YTM_OAUTH_CLIENT_ID` / `YTM_OAUTH_CLIENT_SECRET`. It falls back to
  the browser `AUTH_FILE` when `oauth.json` is absent.
- `setup_auth.py`: make OAuth the default, using the `setup_oauth(...)` device flow with a
  "TV and Limited Input" client. Keep `--browser` for the old flow.
- `cloud-bootstrap.sh` writes `$YTM_OAUTH_JSON` to `OAUTH_FILE`.
- Check that the installed ytmusicapi exposes `setup_oauth` / `OAuthCredentials`.

**C. Relative cross-skill paths.** `ketamine-infusion-playlist/SKILL.md` hardcodes
`ENGINE=~/.claude/skills/yt-music-playlist/...` and `KTM=~/.claude/skills/...`. Rewrite them
relative to the loaded skill dir: the two skills become siblings, so ENGINE is
`../yt-music-playlist/scripts/build_playlist.py`.

## Part 3: Ketamine no-reuse → committed link list

- Point `protocol.json`'s `exclude_dir` at an in-repo directory (the skill's own dir). Then
  `exclude-playlists.json` / `exclude-tracks.json` are committed and reach cloud. The existing
  `ytm.py` load/save logic is unchanged; only the location moves.
- Un-ignore those two files in the skill's `.gitignore`.
- Optionally accept pasted playlist **URLs** (parse `list=`) in `--add-exclude`.
- Document in SKILL.md that `--finalize` / `--add-exclude` now write into the working tree, so
  the updated file gets committed.

## Part 4: Audio analysis in cloud (added 2026-09-24)

Assumes `plans/audio-analysis.md` is implemented. That gives `requirements-audio.txt`
(pinned `essentia-tensorflow==2.1b6.dev1389` + `yt-dlp`), models downloaded from
`essentia.upf.edu`, and feature + embedding caches keyed by videoId.

**A. Install cost.** The essentia wheel is ~140MB and the models ~25MB.

- Prefer the UI **Setup script** (cached) for `requirements-audio.txt` plus the model download.
  The `SessionStart` hook would pay that cost on every session.
- Make `cloud-bootstrap.sh` skip the install when it's already there (check with
  `import essentia`), so the hook stays cheap either way.
- Confirm the cloud image's Python is 3.9–3.13. The pinned wheel has no cp314 build. If the
  image is 3.14, move to `dev1438`, which is cp314-only, and re-verify on macOS.

**B. The real risk: yt-dlp from datacenter IPs.** YouTube often answers cloud/datacenter IPs
with "Sign in to confirm you're not a bot". Mitigations, in order of preference:

1. **Commit the feature caches.** Move `audio-features.json` and `audio-embeddings.json` into
   the repo (beside Part 3's committed exclude lists) with a path change. They're small derived
   numbers, not audio. Anything analyzed locally, including the ~150-track calibration corpus,
   is a cache hit in cloud and needs no download.
2. **Deezer 30s preview fallback.** For uncached tracks where yt-dlp fails, search
   `api.deezer.com` (no auth; tested 2026-09-24) and analyze the 30s preview MP3 with
   `source: "preview"`.
   - Mood, voice, arousal and bpm/key still work, roughly.
   - Loudness contour and start/end transition checks are **skipped** for preview-sourced
     tracks, because the clip is from the middle and may be a different version.
   - Check the match by comparing Deezer vs YTM duration within ±5s, otherwise mark it
     unanalyzed.
3. **yt-dlp cookies: discouraged.** They would be another full-account Google credential in
   plain env vars (see the security caveat).

**C. Network allowlist** (if `Custom`, not `Full`): add `essentia.upf.edu` (models),
`*.googlevideo.com` (yt-dlp media), `api.deezer.com` + `*.dzcdn.net` (previews). PyPI is
already in the defaults.

**D. Local caches when they're committed.** Locally, `analyze_tracks.py` writes into the repo
working tree once the caches move. Treat that like Part 3's exclude lists: commit the updated
cache alongside the session's other changes. The same goes for `voice-verdicts.json`, the
user's listening verdicts, which can't be regenerated at all.

---

## Security caveat (must surface to the user)

Cloud environments have **no secure secrets store**. The OAuth `client_secret` and the
`oauth.json` refresh token would sit as plain env vars in the claude.ai UI. They grant full
access to the YouTube Music / Google account, and anyone with access to that environment can
read them.

Mitigations:

- use a **dedicated or throwaway Google account** for the playlist skills;
- be ready to revoke the OAuth client.

If that risk is unacceptable, `yt-music-playlist` stays local-only and Part 2B is dropped.
Parts 1, 3 and the cached-features side of Part 4 still work.

## Manual / UI steps (cannot be repo-committed)

1. **Network access:** `Full`, or `Custom` with `music.youtube.com`, `*.youtube.com`,
   `*.googleapis.com`, plus Part 4C's hosts. Capture the exact hosts during verification.
2. **Environment variables:** `YTM_OAUTH_JSON`, `YTM_OAUTH_CLIENT_ID`,
   `YTM_OAUTH_CLIENT_SECRET`.
3. **Setup script:** venv + `requirements-audio.txt` + model download (Part 4A).

## Verification

1. `find .claude/skills -maxdepth 2 -name SKILL.md` lists both skills. `git log --follow`
   shows history was preserved.
2. `./install.sh` relinks both skills, and both resolve locally after a restart.
3. **OAuth locally:** `setup_auth.py` device flow, then `build_playlist.py --list-playlists`.
4. **Ketamine no-reuse:** `--add-exclude <url>` writes the committed file, and `--dry-run`
   drops those tracks.
5. **Cloud end-to-end:** push a branch and open a cloud session with the env vars and network
   set. Then:
   - the bootstrap runs and both skills load;
   - a `--dry-run` resolves tracks;
   - a cached track shows audio columns with no download;
   - **one uncached track via yt-dlp**, to learn whether datacenter blocking actually hits; if
     it does, confirm the Deezer fallback gives a `preview`-sourced result.
