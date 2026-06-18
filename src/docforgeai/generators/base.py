"""Generator registry and the LLM-backed document generators.

A Generator maps (RepoProfile, LLMClient) -> GeneratedDoc. LICENSE is purely
deterministic; the prose docs go through the LLM and then the consistency
gate in pipeline.py.
"""
from __future__ import annotations

from collections.abc import Callable, Sequence

from ..config import Config
from ..llm import LLMClient, prompts
from ..models import DocKind, GeneratedDoc, RepoProfile
from .license import render_license

# A Generator maps (profile, client, config, feedback) -> GeneratedDoc.
# `feedback` carries consistency issues from a previous round so the
# self-correcting loop in pipeline.py can ask for a corrected regeneration.
Generator = Callable[[RepoProfile, LLMClient, Config, Sequence[str]], GeneratedDoc]


def _llm_doc(kind: DocKind, filename: str, prompt_fn) -> Generator:
    def gen(profile: RepoProfile, client: LLMClient, config: Config,
            feedback: Sequence[str] = ()) -> GeneratedDoc:
        user = prompt_fn(profile)
        directive = prompts.language_directive(config.language)
        if directive:
            user = user + "\n\n" + directive
        if feedback:
            user = user + "\n\n" + prompts.correction_block(list(feedback))
        content = client.complete(prompts.SYSTEM, user)
        return GeneratedDoc(kind=kind, filename=filename, content=content)

    return gen


def _license_doc(profile: RepoProfile, _client: LLMClient, config: Config,
                 feedback: Sequence[str] = ()) -> GeneratedDoc:
    # License text is deterministic, so the consistency loop never feeds it back.
    # Holder is an actual copyright owner — never the package name. Fall back to
    # an authors collective so the notice is at least conventionally correct.
    holder = config.holder or f"The {profile.name} authors"
    text = render_license(config.license, holder=holder)
    return GeneratedDoc(kind=DocKind.LICENSE, filename="LICENSE", content=text)


GENERATORS: dict[DocKind, Generator] = {
    DocKind.README: _llm_doc(DocKind.README, "README.md", prompts.readme_prompt),
    DocKind.CONTRIBUTING: _llm_doc(DocKind.CONTRIBUTING, "CONTRIBUTING.md", prompts.contributing_prompt),
    DocKind.DEVELOPER_GUIDE: _llm_doc(DocKind.DEVELOPER_GUIDE, "DEVELOPER_GUIDE.md", prompts.developer_guide_prompt),
    DocKind.LICENSE: _license_doc,
}
