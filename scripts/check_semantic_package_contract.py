#!/usr/bin/env python3
"""Check the rehearsed MHM semantic package boundary."""

from __future__ import annotations

import ast
import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOTS = (
    REPO_ROOT / "mhm_core" / "ontology",
    REPO_ROOT / "mhm_core" / "derived_features",
)
EXCLUDED_PATHS = {
    REPO_ROOT / "mhm_core" / "derived_features" / "runner.py",
}
FORBIDDEN_IMPORT_PREFIXES = ("connect_summary", "mhm_core.pipeline")
FORBIDDEN_ASSET_STRINGS = (
    "ontology/connect",
    "external/mhm-ontology",
    "/tmp/connect-ontology",
)


def main() -> int:
    violations: list[str] = []
    for path in _package_files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError as exc:
            violations.append(f"{path}:{exc.lineno}: syntax error: {exc.msg}")
            continue
        for module_name, line_no in _imports(tree):
            if _matches_prefix(module_name, FORBIDDEN_IMPORT_PREFIXES):
                violations.append(f"{path}:{line_no}: forbidden import for mhm-semantics: {module_name}")
        for value, line_no in _string_literals(tree):
            for forbidden in FORBIDDEN_ASSET_STRINGS:
                if forbidden in value:
                    violations.append(
                        f"{path}:{line_no}: implicit CONNECT asset path for mhm-semantics: {forbidden}"
                    )
        if path == REPO_ROOT / "mhm_core" / "derived_features" / "__init__.py":
            exported = _exported_symbols(tree)
            if "run_derived_features_for_participant" in exported:
                violations.append(
                    f"{path}: advertised pipeline-bound runner in mhm-semantics public exports"
                )

    payload = {
        "contract": "mhm-semantics:kernel",
        "status": "ok" if not violations else "failed",
        "violations": violations,
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if not violations else 1


def _package_files() -> list[Path]:
    files: list[Path] = []
    for root in PACKAGE_ROOTS:
        files.extend(path for path in root.rglob("*.py") if path.is_file())
    excluded = {path.resolve() for path in EXCLUDED_PATHS}
    return sorted(path for path in files if path.resolve() not in excluded)


def _imports(tree: ast.AST) -> list[tuple[str, int]]:
    imports: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend((alias.name, node.lineno) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.append((node.module or "", node.lineno))
    return imports


def _string_literals(tree: ast.AST) -> list[tuple[str, int]]:
    values: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            values.append((node.value, node.lineno))
    return values


def _matches_prefix(module_name: str, prefixes: tuple[str, ...]) -> bool:
    return any(module_name == prefix or module_name.startswith(prefix + ".") for prefix in prefixes)


def _exported_symbols(tree: ast.AST) -> set[str]:
    exported: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and target.id == "__all__" for target in node.targets):
            continue
        if isinstance(node.value, (ast.List, ast.Tuple)):
            for item in node.value.elts:
                if isinstance(item, ast.Constant) and isinstance(item.value, str):
                    exported.add(item.value)
    return exported


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
