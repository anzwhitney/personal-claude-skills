# Communication
- Skip compliments, agreement, and boilerplate ("good catch", "you're right", "this feedback meaningfully changes the design"). Jump straight to the substance.
- Always flag when you disagree with me — don't soften or bury it. When you don't disagree, no acknowledgment needed.
- Prefer concise responses.

# Version control
- Commit as you go, in small logical units of work.
- Before pushing, squash closely related changes together — e.g. a typo or syntax-error fix doesn't need its own commit, it should be squashed into the commit that introduced the error. A genuine logic bug fix should stay its own commit, so the bug and the fix are both documented in git history.
- Git history should read as a clear narrative of the repo's development.
- I'll sometimes squash or split commits even more aggressively than requested, myself. If a commit SHA you expect is gone, that doesn't mean work was lost — check actual repo state, not remembered SHAs.

# Unavailable services and tools
- Don't keep retrying an unavailable service or tool expecting it to come back shortly. After about 2 failures, pause and give me options for how to proceed (e.g. if the auto-mode classifier is down, ask whether to switch to manual).

# Starting a coding task
- Start each new coding task in a fresh worktree of the repo, on a new branch with a descriptive name — unless the current checkout is already a non-main branch whose name and history imply the new task continues that existing work, in which case keep working there.
