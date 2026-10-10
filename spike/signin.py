"""Measurement: does a sign-in survive in a Playwright profile?

  uv run python spike/signin.py login PROFILE_DIR URL
      A browser window opens. Sign in, then close the window.

  uv run python spike/signin.py check PROFILE_DIR URL TEXT
      No window. Opens URL with the same profile and says whether TEXT, which
      only a signed-in user sees, is on the page.
"""
from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import Error, sync_playwright


def login(profile: Path, url: str) -> int:
    profile.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(str(profile), headless=False, no_viewport=True)
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(url)
        print("Sign in, then close the browser window.")
        try:
            context.wait_for_event("close", timeout=0)
        except Error:
            pass
    return 0


def check(profile: Path, url: str, text: str) -> int:
    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            str(profile), headless=True, viewport={"width": 1920, "height": 1080}
        )
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(url)
        try:
            page.get_by_text(text).first.wait_for(state="visible", timeout=15_000)
            found = True
        except Error:
            found = False
        landed = page.url
        context.close()
    print(f"landed on: {landed}")
    print(f"'{text}' visible: {'PASS' if found else 'FAIL'}")
    return 0 if found else 1


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "login":
        sys.exit(login(Path(sys.argv[2]), sys.argv[3]))
    if len(sys.argv) == 5 and sys.argv[1] == "check":
        sys.exit(check(Path(sys.argv[2]), sys.argv[3], sys.argv[4]))
    sys.exit(__doc__)
