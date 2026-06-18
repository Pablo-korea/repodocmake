"""Pydantic schemas shared across RepoDocMake.

These types are the strongly-typed contract between the deterministic
analysis layer (repo scanner / AST profiler) and the LLM synthesis layer.
"""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class DocKind(str, Enum):
    README = "README"
    LICENSE = "LICENSE"
    CONTRIBUTING = "CONTRIBUTING"
    DEVELOPER_GUIDE = "DEVELOPER_GUIDE"
    CODE_OF_CONDUCT = "CODE_OF_CONDUCT"
    SECURITY = "SECURITY"


class Mode(str, Enum):
    PR = "pr"          # open a PR with generated docs
    COMMIT = "commit"  # commit directly to the branch
    CHECK = "check"    # fail CI if docs are missing / drifted


class FunctionInfo(BaseModel):
    name: str
    signature: str
    has_docstring: bool = False
    is_public: bool = True


class ModuleInfo(BaseModel):
    path: str
    classes: list[str] = Field(default_factory=list)
    functions: list[FunctionInfo] = Field(default_factory=list)


class RepoProfile(BaseModel):
    """Deterministically extracted facts about a repository.

    Everything here is ground truth pulled from the filesystem / AST, never
    invented by the LLM. The synthesizer consumes this and the consistency
    gate validates LLM output against it.
    """

    name: str
    root: str
    primary_language: str | None = None
    language_breakdown: dict[str, int] = Field(default_factory=dict)
    package_name: str | None = None
    version: str | None = None
    dependencies: list[str] = Field(default_factory=list)
    manifests: list[str] = Field(default_factory=list)  # e.g. requirements.txt
    entrypoints: list[str] = Field(default_factory=list)
    existing_docs: list[str] = Field(default_factory=list)
    modules: list[ModuleInfo] = Field(default_factory=list)
    summary_hint: str | None = None


class GeneratedDoc(BaseModel):
    kind: DocKind
    filename: str
    content: str
    skipped: bool = False
    reason: str | None = None
