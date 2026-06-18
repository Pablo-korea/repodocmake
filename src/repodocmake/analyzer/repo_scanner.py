"""Deterministic repository scanner.

Walks a checked-out repo and extracts ground-truth facts: language mix,
package metadata, entrypoints and which standard docs already exist. No LLM
involved here — this is the factual backbone the synthesizer is held to.
"""
from __future__ import annotations

import ast
import configparser
import json
import os
import tomllib
from pathlib import Path

from ..models import RepoProfile
from .ast_profiler import profile_python_modules

# extension -> language label
_LANG_BY_EXT = {
    ".py": "Python",
    ".js": "JavaScript",
    ".ts": "TypeScript",
    ".go": "Go",
    ".rs": "Rust",
    ".java": "Java",
    ".rb": "Ruby",
}

_IGNORE_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", "dist", "build", ".tox"}

_DOC_FILES = {
    "README": ("readme.md", "readme.rst", "readme"),
    "LICENSE": ("license", "license.md", "license.txt"),
    "CONTRIBUTING": ("contributing.md",),
    "CODE_OF_CONDUCT": ("code_of_conduct.md",),
    "SECURITY": ("security.md",),
    "DEVELOPER_GUIDE": ("developer_guide.md", "developerguide.md", "docs/developer_guide.md"),
}


def _detect_languages(root: Path) -> dict[str, int]:
    counts: dict[str, int] = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _IGNORE_DIRS]
        for fn in filenames:
            lang = _LANG_BY_EXT.get(Path(fn).suffix.lower())
            if lang:
                counts[lang] = counts.get(lang, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: kv[1], reverse=True))


def _read_pyproject(root: Path) -> tuple[str | None, str | None, list[str]]:
    pp = root / "pyproject.toml"
    if not pp.exists():
        return None, None, []
    try:
        data = tomllib.loads(pp.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, OSError):
        return None, None, []
    project = data.get("project", {})
    return project.get("name"), project.get("version"), list(project.get("dependencies", []))


def _clean_version(value: str | None) -> str | None:
    # setuptools allows directives like `attr: pkg.__version__` / `file: VERSION`
    # which aren't literal versions — treat those as unspecified.
    if value and value.split(":", 1)[0].strip() in ("attr", "file"):
        return None
    return value


def _read_setup_cfg(root: Path) -> tuple[str | None, str | None, list[str]]:
    sc = root / "setup.cfg"
    if not sc.exists():
        return None, None, []
    parser = configparser.ConfigParser()
    try:
        parser.read(sc, encoding="utf-8")
    except (configparser.Error, OSError):
        return None, None, []
    name = parser.get("metadata", "name", fallback=None)
    version = _clean_version(parser.get("metadata", "version", fallback=None))
    raw = parser.get("options", "install_requires", fallback="")
    deps = [line.strip() for line in raw.splitlines() if line.strip()]
    return name, version, deps


def _setup_kwargs(tree: ast.Module) -> dict[str, ast.expr]:
    """Find the `setup(...)` call and return its keyword args (AST nodes)."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        is_setup = (isinstance(func, ast.Name) and func.id == "setup") or (
            isinstance(func, ast.Attribute) and func.attr == "setup"
        )
        if is_setup:
            return {kw.arg: kw.value for kw in node.keywords if kw.arg}
    return {}


def _str_literal(node: ast.expr | None) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _str_list(node: ast.expr | None) -> list[str]:
    if isinstance(node, (ast.List, ast.Tuple)):
        return [e.value for e in node.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)]
    return []


def _read_setup_py(root: Path) -> tuple[str | None, str | None, list[str]]:
    """Extract metadata from setup.py via AST — never executes the file."""
    sp = root / "setup.py"
    if not sp.exists():
        return None, None, []
    try:
        tree = ast.parse(sp.read_text(encoding="utf-8"))
    except (SyntaxError, OSError, UnicodeDecodeError):
        return None, None, []
    kwargs = _setup_kwargs(tree)
    return (
        _str_literal(kwargs.get("name")),
        _clean_version(_str_literal(kwargs.get("version"))),
        _str_list(kwargs.get("install_requires")),
    )


def _read_package_json(root: Path) -> tuple[str | None, str | None, list[str]]:
    """Read name / version / runtime deps from a package.json (JS/TS projects)."""
    pj = root / "package.json"
    if not pj.exists():
        return None, None, []
    try:
        data = json.loads(pj.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None, None, []
    deps = sorted(data.get("dependencies", {}))
    return data.get("name"), data.get("version"), deps


def _read_metadata(root: Path) -> tuple[str | None, str | None, list[str]]:
    """Resolve package name / version / deps across manifest formats.

    Python manifests are tried in order of authority (pyproject -> setup.cfg ->
    setup.py); name/version come from the first that declares them, deps from
    the first non-empty source, falling back to requirements.txt. package.json
    is consulted only when no Python manifest contributed anything, so a Python
    repo that merely ships a frontend package.json is never mislabeled by it.
    """
    name = version = None
    deps: list[str] = []
    for reader in (_read_pyproject, _read_setup_cfg, _read_setup_py):
        n, v, d = reader(root)
        name = name or n
        version = version or v
        if not deps and d:
            deps = d
    if not deps:
        deps = _read_requirements(root)
    if not name and not deps:  # not a Python project — try JS/TS
        name, version, deps = _read_package_json(root)
    return name, version, deps


def _read_requirements(root: Path) -> list[str]:
    """Parse requirements.txt into a list of requirement strings.

    Skips comments, blank lines, options (`-r`, `-e`, `--hash`, ...) and strips
    environment markers, keeping the version-pinned spec (e.g. `aiohttp==3.12`).
    """
    rq = root / "requirements.txt"
    if not rq.exists():
        return []
    deps: list[str] = []
    try:
        lines = rq.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    for raw in lines:
        line = raw.split("#", 1)[0].strip()
        if not line or line.startswith("-"):  # blank, comment, or pip option
            continue
        line = line.split(";", 1)[0].strip()  # drop env markers
        if line:
            deps.append(line)
    return deps


# Manifest file -> the install command a contributor would actually run.
_MANIFESTS = ("pyproject.toml", "requirements.txt", "setup.py", "setup.cfg", "package.json")


def _find_manifests(root: Path) -> list[str]:
    return [m for m in _MANIFESTS if (root / m).exists()]


def _find_existing_docs(root: Path) -> list[str]:
    present: list[str] = []
    lower_index = {p.relative_to(root).as_posix().lower(): p for p in root.rglob("*") if p.is_file()}
    for kind, candidates in _DOC_FILES.items():
        if any(c in lower_index for c in candidates):
            present.append(kind)
    return present


def _find_entrypoints(root: Path) -> list[str]:
    eps: list[str] = []
    for name in ("__main__.py", "main.py", "cli.py", "app.py"):
        for hit in root.rglob(name):
            if not any(part in _IGNORE_DIRS for part in hit.parts):
                eps.append(hit.relative_to(root).as_posix())
    return sorted(set(eps))


def scan_repository(root: str) -> RepoProfile:
    root_path = Path(root).resolve()
    langs = _detect_languages(root_path)
    pkg_name, version, deps = _read_metadata(root_path)
    primary = next(iter(langs), None)

    modules = profile_python_modules(root_path, _IGNORE_DIRS) if primary == "Python" else []

    return RepoProfile(
        name=pkg_name or root_path.name,
        root=str(root_path),
        primary_language=primary,
        language_breakdown=langs,
        package_name=pkg_name,
        version=version,
        dependencies=deps,
        manifests=_find_manifests(root_path),
        entrypoints=_find_entrypoints(root_path),
        existing_docs=_find_existing_docs(root_path),
        modules=modules,
    )
