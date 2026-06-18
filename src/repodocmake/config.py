"""Runtime configuration, resolved from CLI flags / Action inputs / env."""
from __future__ import annotations

import os
from dataclasses import dataclass, field

from .models import DocKind, Mode

DEFAULT_FILES = [DocKind.README, DocKind.LICENSE, DocKind.CONTRIBUTING, DocKind.DEVELOPER_GUIDE]


@dataclass
class Config:
    target: str = "."                      # local path or git URL
    files: list[DocKind] = field(default_factory=lambda: list(DEFAULT_FILES))
    license: str = "Apache-2.0"            # SPDX identifier
    holder: str | None = None              # LICENSE copyright holder (else derived)
    language: str = "en"                   # doc language: en | ko | ko+en (bilingual)
    mode: Mode = Mode.PR
    out_dir: str | None = None             # for --dry-run / local preview
    dry_run: bool = False
    force: bool = False                    # overwrite existing docs
    provider: str = "anthropic"
    model: str | None = None
    correction_rounds: int = 2             # max self-correcting regen rounds

    @classmethod
    def from_env(cls) -> Config:
        """Build config from GitHub Action `INPUT_*` env vars."""
        files = [
            DocKind(x.strip())
            for x in os.environ.get("INPUT_FILES", "README,LICENSE,CONTRIBUTING,DEVELOPER_GUIDE").split(",")
            if x.strip()
        ]
        return cls(
            target=os.environ.get("GITHUB_WORKSPACE", "."),
            files=files,
            license=os.environ.get("INPUT_LICENSE", "Apache-2.0"),
            holder=os.environ.get("INPUT_HOLDER") or None,
            language=os.environ.get("INPUT_LANGUAGE") or os.environ.get("REPODOCMAKE_LANGUAGE") or "en",
            mode=Mode(os.environ.get("INPUT_MODE", "pr")),
            provider=os.environ.get("REPODOCMAKE_LLM_PROVIDER", os.environ.get("INPUT_LLM-PROVIDER", "anthropic")),
            force=os.environ.get("INPUT_FORCE", "false").lower() == "true",
        )
