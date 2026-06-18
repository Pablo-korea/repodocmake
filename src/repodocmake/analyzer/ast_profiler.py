"""Python AST profiler.

Extracts the public API surface (modules, classes, functions, signatures,
docstring presence) so the LLM is told precisely what the project exposes
rather than guessing from file names. tree-sitter slots in here later for
multi-language support without changing the downstream contract.
"""
from __future__ import annotations

import ast
from pathlib import Path

from ..models import FunctionInfo, ModuleInfo


def _format_signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    args = [a.arg for a in node.args.args]
    if node.args.vararg:
        args.append("*" + node.args.vararg.arg)
    if node.args.kwarg:
        args.append("**" + node.args.kwarg.arg)
    prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
    return f"{prefix} {node.name}({', '.join(args)})"


def _profile_file(path: Path, rel: str) -> ModuleInfo | None:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, OSError, UnicodeDecodeError):
        return None

    classes: list[str] = []
    functions: list[FunctionInfo] = []
    for node in tree.body:  # module-level only — top of the API surface
        if isinstance(node, ast.ClassDef):
            classes.append(node.name)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions.append(
                FunctionInfo(
                    name=node.name,
                    signature=_format_signature(node),
                    has_docstring=ast.get_docstring(node) is not None,
                    is_public=not node.name.startswith("_"),
                )
            )
    if not classes and not functions:
        return None
    return ModuleInfo(path=rel, classes=classes, functions=functions)


def profile_python_modules(root: Path, ignore_dirs: set[str], limit: int = 50) -> list[ModuleInfo]:
    modules: list[ModuleInfo] = []
    for py in sorted(root.rglob("*.py")):
        if any(part in ignore_dirs for part in py.parts):
            continue
        rel = py.relative_to(root).as_posix()
        info = _profile_file(py, rel)
        if info:
            modules.append(info)
        if len(modules) >= limit:  # keep LLM context bounded on large repos
            break
    return modules
