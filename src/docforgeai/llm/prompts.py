"""Prompt builders. Each turns a RepoProfile into a compact, factual context
block so the LLM writes docs grounded in real code, not invention.
"""
from __future__ import annotations

from ..models import RepoProfile

SYSTEM = (
    "You are DocForgeAI, an expert open-source maintainer. You write accurate, "
    "concise project documentation. Only state facts supported by the provided "
    "repository profile. Never invent install commands, package names, or APIs."
)


def render_profile(profile: RepoProfile) -> str:
    lines = [
        f"Project name: {profile.name}",
        f"Primary language: {profile.primary_language}",
        f"Package name: {profile.package_name or '(none)'}",
        f"Version: {profile.version or '(unspecified)'}",
        f"Languages: {profile.language_breakdown}",
        f"Entry points: {', '.join(profile.entrypoints) or '(none found)'}",
        f"Dependency manifests: {', '.join(profile.manifests) or '(none)'}",
        f"Dependencies: {', '.join(profile.dependencies[:20]) or '(none)'}",
        f"Existing docs: {', '.join(profile.existing_docs) or '(none)'}",
        "Public API surface:",
    ]
    for m in profile.modules[:25]:
        api = ", ".join(m.classes + [f.name for f in m.functions if f.is_public])
        if api:
            lines.append(f"  - {m.path}: {api}")
    return "\n".join(lines)


def readme_prompt(profile: RepoProfile) -> str:
    return (
        "Write a complete README.md in Markdown for the project below. Include: "
        "title, one-line description, key features, installation, usage example, "
        "and a contributing pointer. Base everything on these facts:\n\n"
        + render_profile(profile)
    )


def contributing_prompt(profile: RepoProfile) -> str:
    return (
        "Write a CONTRIBUTING.md for the project below: how to set up a dev "
        "environment, run tests, and submit a PR. Use the real package/test "
        "tooling implied by the facts:\n\n" + render_profile(profile)
    )


def developer_guide_prompt(profile: RepoProfile) -> str:
    return (
        "Write a DEVELOPER_GUIDE.md explaining the architecture and module "
        "layout for new contributors, based on the public API surface below:\n\n"
        + render_profile(profile)
    )


# Language directives appended to every doc prompt. `ko+en` produces bilingual
# docs; identifiers and commands are kept verbatim so the consistency gate
# (package name / install commands) still matches.
_LANGUAGE_DIRECTIVES = {
    "en": "",
    "ko": "Write the entire document in Korean. Keep code blocks, commands, "
          "package names, and identifiers unchanged (do not translate them).",
    "ko+en": (
        "Write the document bilingually in BOTH Korean and English. For each "
        "section, write the prose in English first, then immediately provide "
        "the Korean translation below it. Keep code blocks, commands, package "
        "names, URLs, and identifiers unchanged (do not translate them), and "
        "write each section heading in both languages, e.g. "
        "'## Installation / 설치'."
    ),
}

_LANGUAGE_ALIASES = {
    "bilingual": "ko+en", "en+ko": "ko+en", "ko-en": "ko+en", "enko": "ko+en",
    "kr": "ko", "korean": "ko", "english": "en",
}


def language_directive(language: str | None) -> str:
    key = (language or "en").lower().replace(" ", "")
    key = _LANGUAGE_ALIASES.get(key, key)
    return _LANGUAGE_DIRECTIVES.get(key, "")


def correction_block(issues: list[str]) -> str:
    """Corrective context fed back into the LLM by the self-correcting loop.

    When the consistency gate rejects a draft, these instructions are appended
    to the original prompt so the next round fixes the exact factual problems
    instead of regenerating blindly.
    """
    bullets = "\n".join(f"- {issue}" for issue in issues)
    return (
        "IMPORTANT — your previous draft FAILED these factual consistency checks:\n"
        f"{bullets}\n\n"
        "Regenerate the document and fix every issue above. Use ONLY the real "
        "package name, install commands, dependencies, and APIs from the "
        "repository profile. Do not invent or rename anything."
    )
