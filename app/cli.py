"""One-shot commands for GitHub Actions (the Docker web app uses the long-running loop in bot.py instead).

    python -m app.cli scan [--force]   scan once if the bot is started (--force: even if stopped)
    python -m app.cli remember         remember all current listings without notifying
"""

from __future__ import annotations

import hashlib
import json
import os
import sys

from .bot import Bot
from .storage import load_settings, load_state


def _fingerprint() -> str:
    # Only remembered listings and matches decide whether the state is worth committing back to the repo;
    # a timestamp-only change every 10 minutes would flood the history with commits.
    s = load_state()
    return hashlib.sha256(json.dumps([sorted(s.seen), s.matches], default=str).encode()).hexdigest()


def _output(name: str, value: str) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"{name}={value}\n")


def main(argv: list[str]) -> int:
    command = argv[0] if argv else "scan"
    before = _fingerprint()
    bot = Bot()

    if command == "remember":
        print(f"Remembered {bot.remember_current()} listings")
        ok = True
    elif command == "scan":
        if not load_settings().running and "--force" not in argv:
            print("Bot is stopped; nothing to do.")
            _output("changed", "false")
            return 0
        ok, summary = bot.scan_once(load_settings())
        print(summary)
    else:
        print(__doc__)
        return 2

    _output("changed", "true" if _fingerprint() != before else "false")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
