"""Command-line entrypoint: `docforgeai generate <target> ...`."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import click
from dotenv import load_dotenv

from . import vcs
from .config import Config
from .models import DocKind, Mode
from .pipeline import run


@click.group()
@click.version_option()
def main() -> None:
    """DocForgeAI — generate OSS docs by analyzing a repository."""
    # Load API keys / settings from a local .env (real LLM runs), if present.
    load_dotenv()


@main.command()
@click.argument("target", default=".")
@click.option("--files", default="README,LICENSE,CONTRIBUTING,DEVELOPER_GUIDE",
              help="Comma-separated doc kinds to generate.")
@click.option("--license", "license_id", default="Apache-2.0", help="SPDX license identifier.")
@click.option("--holder", default=None, help="LICENSE copyright holder (else 'The <project> authors').")
@click.option("--language", default=None,
              help="Doc language: en | ko | ko+en (bilingual). Else DOCFORGEAI_LANGUAGE env, else en.")
@click.option("--mode", type=click.Choice([m.value for m in Mode]), default="pr")
@click.option("--out", "out_dir", default=None, help="Write generated docs to this directory.")
@click.option("--dry-run", is_flag=True, help="Use mock LLM, do not call any API or write files.")
@click.option("--force", is_flag=True, help="Overwrite existing docs.")
@click.option("--commit", "do_commit", is_flag=True,
              help="After writing, git add + commit the docs in the target repo.")
@click.option("--provider", default=None,
              help="LLM provider (else DOCFORGEAI_LLM_PROVIDER env, else anthropic).")
@click.option("--model", default=None, help="Override the LLM model (else provider default / DOCFORGEAI_LLM_MODEL).")
def generate(target, files, license_id, holder, language, mode, out_dir, dry_run, force, do_commit, provider, model):
    """Analyze TARGET (path or git URL) and generate documentation.

    With --out, docs are written to that preview directory. Without --out, docs
    are written in place into TARGET (e.g. a locally cloned repo); add --commit
    to also commit them there.
    """
    # Explicit flag wins; otherwise honor the single env-var switch (.env).
    provider = provider or os.environ.get("DOCFORGEAI_LLM_PROVIDER", "anthropic")
    language = language or os.environ.get("DOCFORGEAI_LANGUAGE", "en")
    config = Config(
        target=target,
        files=[DocKind(f.strip()) for f in files.split(",") if f.strip()],
        license=license_id,
        holder=holder,
        language=language,
        mode=Mode(mode),
        out_dir=out_dir,
        dry_run=dry_run,
        force=force,
        provider=provider,
        model=model,
    )
    docs = run(config)  # writes to out_dir itself when --out is given

    # No --out: write in place into the target repo (skip in dry-run, which is
    # a no-touch preview). run() already wrote when --out was given.
    in_place = out_dir is None and not dry_run and os.path.isdir(target)
    written: list[str] = []
    if in_place:
        for d in docs:
            if not d.skipped:
                Path(target, d.filename).write_text(d.content, encoding="utf-8")
                written.append(d.filename)

    generated = sum(not d.skipped for d in docs)
    for d in docs:
        status = "SKIP" if d.skipped else "OK  "
        note = f" ({d.reason})" if d.reason else ""
        click.echo(f"[{status}] {d.filename}{note}")
    if generated:
        click.echo(f"\nGenerated {generated} document(s).")

    if do_commit:
        if not in_place:
            click.echo("--commit needs in-place generation (omit --out, don't use --dry-run).")
        elif not written:
            click.echo("Nothing to commit.")
        elif vcs.commit_mode(target, written):
            click.echo(f"[commit] committed {len(written)} doc(s) to {target}")
        else:
            click.echo("[commit] no changes to commit")
    return 0


if __name__ == "__main__":
    sys.exit(main())
