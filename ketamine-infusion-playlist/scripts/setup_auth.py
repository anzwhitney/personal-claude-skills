#!/usr/bin/env python3
"""One-time (or occasional) YouTube Music browser auth setup.

Wraps `ytmusicapi.setup()`, which walks the user through pasting request
headers copied from music.youtube.com in their browser's dev tools, and
writes the result to the skill's runtime state dir (outside the git repo).

Usage:
    python3 setup_auth.py                       # reuse existing auth if it still works
    python3 setup_auth.py --force                # redo the browser-header capture (interactive paste)
    python3 setup_auth.py --headers-file PATH     # read pasted headers from a file instead of stdin

The interactive paste (--force with no --headers-file) reads pasted lines via
input() in a loop, which goes through the terminal's canonical line buffer.
The browser's `cookie` header is often several KB on one line, which can
exceed the terminal's per-line buffer limit and stall the paste (Ctrl-D
appears to do nothing). If that happens, use --headers-file instead: paste
the copied headers into a plain text file with a text editor (no line-length
limit there), save it, and pass its path.
"""
from __future__ import annotations

import argparse
import re
import sys

from ytm import AUTH_FILE, STATE_DIR, ensure_state_dir

_REQUEST_LINE_RE = re.compile(r"^(GET|POST|PUT|DELETE|HEAD|OPTIONS|PATCH) .+ HTTP/[\d.]+$")


def clean_headers_raw(raw: str) -> str:
    """Strip the leading HTTP request line and blank lines.

    ytmusicapi's parser has a code path for Chrome's "key on one line, value
    on the next" copy format. A leading request line (which Firefox's "Copy
    Request Headers" includes) combined with a trailing blank line trips
    that path: it stores the request line as a pending header name and the
    blank line as its value, producing a bogus header whose name contains
    spaces/colons. Google's API rejects that with an HTML 400 page that
    ytmusicapi then fails to json-parse.
    """
    lines = [line for line in raw.splitlines() if line.strip() and not _REQUEST_LINE_RE.match(line.strip())]
    return "\n".join(lines)


def _strip_malformed_header_keys(auth_path) -> None:
    """Drop any saved header whose key isn't a plausible HTTP header name.

    Belt-and-suspenders for the request-line mis-parse described in
    clean_headers_raw(): catches it even if it slips in via the interactive
    (non --headers-file) paste path, which isn't pre-cleaned.
    """
    import json

    with open(auth_path, encoding="utf-8") as f:
        headers = json.load(f)
    cleaned = {k: v for k, v in headers.items() if re.match(r"^[A-Za-z0-9-]+$", k)}
    if cleaned != headers:
        dropped = set(headers) - set(cleaned)
        print(f"  dropped malformed header key(s): {dropped}")
        with open(auth_path, "w", encoding="utf-8") as f:
            json.dump(cleaned, f, indent=4, sort_keys=True)


def verify(auth_path: str) -> bool:
    from ytmusicapi import YTMusic

    try:
        yt = YTMusic(auth_path)
        results = yt.search("Max Richter", filter="songs", limit=1)
    except Exception as exc:  # noqa: BLE001
        print(f"  auth check failed: {exc}")
        return False
    if not results:
        print("  auth check: search returned no results (unexpected, but auth call succeeded)")
        return True
    print(f"  auth check OK — sample result: {results[0].get('title')!r}")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="redo browser-header capture even if a working auth file exists")
    parser.add_argument(
        "--headers-file",
        metavar="PATH",
        help="read pasted request headers from this file instead of prompting interactively "
        "(avoids the terminal's per-line paste limit; see module docstring)",
    )
    args = parser.parse_args()

    ensure_state_dir()
    print(f"State dir: {STATE_DIR}")

    if AUTH_FILE.exists() and not args.force:
        print(f"Found existing auth file at {AUTH_FILE}, verifying...")
        if verify(str(AUTH_FILE)):
            print("Existing auth is valid. Nothing to do (pass --force to redo).")
            return 0
        print("Existing auth is stale. Re-running the capture flow.")

    print()
    print("Follow the prompts below. In short:")
    print("  1. Open music.youtube.com in your browser, logged in.")
    print("  2. Open DevTools (Cmd+Option+I) -> Network tab.")
    print("  3. Reload / click around; filter requests for 'browse'.")
    print("  4. Click a POST request with status 200.")
    print("  5. Copy the request headers (Firefox: right-click -> Copy > Copy Request Headers).")
    if args.headers_file:
        print(f"  6. Already saved to {args.headers_file} — reading from there.")
    else:
        print("  6. Paste them when prompted, then press Ctrl-D (or enter a blank line) to finish.")
        print("     (If the paste stalls — the cookie header is often too long for the terminal's")
        print("     line buffer — Ctrl-C out and rerun with --headers-file instead: paste into a")
        print("     text file, save it, then pass its path.)")
    print()

    from ytmusicapi import setup

    headers_raw = None
    if args.headers_file:
        with open(args.headers_file, encoding="utf-8") as f:
            headers_raw = clean_headers_raw(f.read())

    setup(filepath=str(AUTH_FILE), headers_raw=headers_raw)
    _strip_malformed_header_keys(AUTH_FILE)

    print()
    print("Verifying new auth file...")
    if not verify(str(AUTH_FILE)):
        print("Auth capture did not verify. Check the headers and try again with --force.")
        return 1

    print(f"Auth saved to {AUTH_FILE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
