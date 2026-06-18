"""Orchestration: scan -> generate -> consistency-gate -> write.

This is the hybrid loop the project is built around. Deterministic facts come
from the scanner; the LLM synthesizes prose; the consistency gate holds that
prose to the facts (package name / entrypoints must actually appear), and the
gate is where a self-correcting regeneration round hooks in.
"""
from __future__ import annotations

import re
from pathlib import Path

from .analyzer import scan_repository
from .config import Config
from .generators import GENERATORS
from .llm import LLMClient, get_client
from .models import DocKind, GeneratedDoc, RepoProfile

# Prose docs whose claims are checked against the deterministic profile.
_PROSE_KINDS = {DocKind.README, DocKind.CONTRIBUTING, DocKind.DEVELOPER_GUIDE}

# Captures the install target of `pip install <target>`, skipping flags like -e.
_PIP_INSTALL = re.compile(r"pip install\s+(?:-[^\s]+\s+)*([A-Za-z0-9._\-\[\]]+)")


def _pkg_base(name: str) -> str:
    """Normalize a requirement to a comparable base name.

    Strips version specifiers / extras (`pydantic>=2.6`, `repodocmake[dev]`) and
    folds the PyPI-equivalent `_`/`-` so comparisons are robust.
    """
    base = re.split(r"[<>=!;\[ ]", name.strip())[0]
    return base.replace("_", "-").lower()


def _consistency_issues(doc: GeneratedDoc, profile: RepoProfile) -> list[str]:
    """Cheap factual checks: does the prose contradict ground truth?

    These are deliberately high-precision (only fire on clear contradictions)
    so the self-correcting loop never chases a phantom problem.
    """
    issues: list[str] = []
    if doc.kind not in _PROSE_KINDS:
        return issues

    pkg = profile.package_name
    if pkg and doc.kind == DocKind.README and pkg not in doc.content:
        issues.append(f"README never mentions the package name '{pkg}'")

    if pkg:
        # An install command must reference the real package or a real
        # dependency — anything else is an invented (hallucinated) name.
        known = {_pkg_base(pkg)} | {_pkg_base(d) for d in profile.dependencies}
        for target in _PIP_INSTALL.findall(doc.content):
            if target == "." or _pkg_base(target) in known:
                continue
            issues.append(
                f"'pip install {target}' refers to an unknown package; "
                f"the real package is '{pkg}'"
            )
    return issues


def _synthesize(gen, profile: RepoProfile, client: LLMClient,
                config: Config) -> GeneratedDoc:
    """Generate a doc, then run the consistency gate with self-correction.

    Round 0 is the initial draft; each failing round feeds the exact issues
    back into the generator and regenerates, up to config.correction_rounds.
    """
    doc = gen(profile, client, config)
    issues = _consistency_issues(doc, profile)

    rounds = 0
    while issues and rounds < config.correction_rounds:
        rounds += 1
        doc = gen(profile, client, config, issues)
        issues = _consistency_issues(doc, profile)

    if issues:
        doc.reason = (
            f"consistency warnings after {rounds} correction round(s): "
            + "; ".join(issues)
        )
    elif rounds:
        doc.reason = f"consistency gate passed after {rounds} correction round(s)"
    return doc


def missing_docs(config: Config) -> list[str]:
    """Requested docs that RepoDocMake can generate but that don't yet exist.

    This is the `check` mode core: a purely deterministic drift signal that
    touches no files and makes no LLM calls. Docs with no generator (e.g.
    SECURITY) are excluded so they never trigger a spurious CI failure.
    """
    profile = scan_repository(config.target)
    return [
        kind.value
        for kind in config.files
        if kind in GENERATORS and kind.value not in profile.existing_docs
    ]


def run(config: Config) -> list[GeneratedDoc]:
    profile = scan_repository(config.target)
    client = get_client(config.provider, config.model, mock=config.dry_run)

    results: list[GeneratedDoc] = []
    for kind in config.files:
        gen = GENERATORS.get(kind)
        if gen is None:
            results.append(GeneratedDoc(kind=kind, filename=kind.value, content="", skipped=True, reason="no generator"))
            continue

        if kind.value in profile.existing_docs and not config.force:
            results.append(
                GeneratedDoc(kind=kind, filename=kind.value, content="", skipped=True,
                             reason="already exists (use --force / pr mode to update)")
            )
            continue

        results.append(_synthesize(gen, profile, client, config))

    # --out is an explicit preview destination (never the source repo), so we
    # write there even in dry-run. Dry-run only means "no real LLM call" and
    # "do not touch the analyzed repo in place".
    if config.out_dir:
        _write_docs(results, config.out_dir)
    return results


def _write_docs(docs: list[GeneratedDoc], out_dir: str) -> None:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    for d in docs:
        if not d.skipped:
            (out / d.filename).write_text(d.content, encoding="utf-8")
