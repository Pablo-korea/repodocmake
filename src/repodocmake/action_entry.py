"""GitHub Action entrypoint (invoked by the Docker container).

Reads INPUT_* env vars, then dispatches on the mode:

  - check : detect missing/drifted docs. Writes nothing, makes no LLM call,
            and exits non-zero so CI fails on doc drift.
  - commit: generate docs, write them, and commit to the current branch.
  - pr    : generate docs, write them on a fresh branch, push, and open a PR.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from . import vcs
from .config import Config
from .models import Mode
from .pipeline import missing_docs, run


def _set_output(name: str, value: str) -> None:
    out_file = os.environ.get("GITHUB_OUTPUT")
    if out_file:
        with open(out_file, "a", encoding="utf-8") as fh:
            fh.write(f"{name}={value}\n")


def _run_check(config: Config) -> int:
    missing = missing_docs(config)
    _set_output("missing-files", ",".join(missing))
    if missing:
        print(f"::error::Documentation missing or out of date: {', '.join(missing)} (check mode).")
        return 1
    print("All requested documentation is present (check mode).")
    return 0


def _generate_and_write(config: Config) -> list[str]:
    """Generate docs and write the non-skipped ones into the workspace."""
    docs = run(config)  # out_dir is None here, so run() writes nothing itself
    written: list[str] = []
    for d in docs:
        if d.skipped:
            print(f"[skipped]   {d.filename}: {d.reason}")
            continue
        Path(config.target, d.filename).write_text(d.content, encoding="utf-8")
        written.append(d.filename)
        note = f" ({d.reason})" if d.reason else ""
        print(f"[generated] {d.filename}{note}")

    _set_output("generated-count", str(len(written)))
    _set_output("generated-files", ",".join(written))
    return written


def main() -> int:
    config = Config.from_env()

    if config.mode == Mode.CHECK:
        return _run_check(config)

    written = _generate_and_write(config)
    if not written:
        print("Nothing to do — all requested docs already exist.")
        return 0

    if config.mode == Mode.COMMIT:
        if vcs.commit_mode(config.target, written):
            print("[commit] committed generated docs to the current branch")
    elif config.mode == Mode.PR:
        url = vcs.pr_mode(config.target, written)
        if url:
            print(f"[pr] opened pull request: {url}")
            _set_output("pr-url", url)
    return 0


if __name__ == "__main__":
    sys.exit(main())
