"""Registry helpers for derived feature specs."""
from __future__ import annotations

import ast
import fnmatch
import importlib.util
import json
import os
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Set

import yaml

from .inline_metadata import parse_inline_metadata

def _decorator_name(node: ast.AST) -> Optional[str]:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _load_source_text(path: Path) -> str:
    if path.suffix == ".ipynb":
        raw = json.loads(path.read_text(encoding="utf-8"))
        cells = raw.get("cells") or []
        code_chunks: List[str] = []
        for cell in cells:
            if not isinstance(cell, Mapping):
                continue
            if cell.get("cell_type") != "code":
                continue
            source = cell.get("source") or []
            if isinstance(source, list):
                text = "".join(str(part) for part in source)
            else:
                text = str(source)
            if text.strip():
                code_chunks.append(text)
        return "\n\n".join(code_chunks)
    return path.read_text(encoding="utf-8")


def load_decorator_metadata(script_path: Path, *, _visited: Optional[Set[Path]] = None) -> Dict[str, Any]:
    resolved_path = script_path.resolve()
    visited = set(_visited or set())
    if resolved_path in visited:
        return {
            "outputs": [],
            "computation": {},
            "defaults": {},
            "feature_id": None,
        }
    visited.add(resolved_path)
    source_text = _load_source_text(script_path)
    tree = ast.parse(source_text, filename=str(script_path))
    outputs: List[Dict[str, Any]] = []
    computation: Dict[str, Any] = {}
    defaults: Dict[str, Any] = {}
    script_feature_id: Optional[str] = None
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "feature_id":
                    try:
                        value = ast.literal_eval(node.value)
                    except Exception:
                        value = None
                    if isinstance(value, str) and value.strip():
                        script_feature_id = value.strip()
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name) and node.target.id == "feature_id" and node.value is not None:
                try:
                    value = ast.literal_eval(node.value)
                except Exception:
                    value = None
                if isinstance(value, str) and value.strip():
                    script_feature_id = value.strip()
        if isinstance(node, ast.FunctionDef) and node.name == "compute":
            for decorator in node.decorator_list:
                if not isinstance(decorator, ast.Call):
                    continue
                name = _decorator_name(decorator.func)
                if name == "odim_outputs":
                    if decorator.args:
                        try:
                            raw = ast.literal_eval(decorator.args[0])
                        except Exception:
                            raw = None
                        if isinstance(raw, list):
                            outputs = [dict(item) for item in raw if isinstance(item, dict)]
                    for kw in decorator.keywords:
                        if kw.arg == "outputs":
                            try:
                                raw = ast.literal_eval(kw.value)
                            except Exception:
                                raw = None
                            if isinstance(raw, list):
                                outputs = [dict(item) for item in raw if isinstance(item, dict)]
                elif name == "odim_computation":
                    for kw in decorator.keywords:
                        if not kw.arg:
                            continue
                        try:
                            computation[kw.arg] = ast.literal_eval(kw.value)
                        except Exception:
                            continue
                elif name == "odim_defaults":
                    for kw in decorator.keywords:
                        if not kw.arg:
                            continue
                        try:
                            defaults[kw.arg] = ast.literal_eval(kw.value)
                        except Exception:
                            continue
    metadata = {
        "outputs": outputs,
        "computation": computation,
        "defaults": defaults,
        "feature_id": script_feature_id,
    }
    if _metadata_is_empty(metadata):
        wrapper_target = _star_import_wrapper_target(tree)
        if wrapper_target is not None:
            return load_decorator_metadata(wrapper_target, _visited=visited)
    return metadata


def _metadata_is_empty(metadata: Mapping[str, Any]) -> bool:
    return not (
        metadata.get("outputs")
        or metadata.get("computation")
        or metadata.get("defaults")
        or metadata.get("feature_id")
    )


def _star_import_wrapper_target(tree: ast.Module) -> Optional[Path]:
    imports: list[ast.ImportFrom] = []
    for node in tree.body:
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            continue
        if isinstance(node, ast.ImportFrom):
            if node.module == "__future__":
                continue
            imports.append(node)
            continue
        if isinstance(node, ast.Import) and all(alias.name == "__future__" for alias in node.names):
            continue
        return None
    if len(imports) != 1:
        return None
    import_node = imports[0]
    if import_node.level != 0 or not import_node.module:
        return None
    if not any(alias.name == "*" for alias in import_node.names):
        return None
    spec = importlib.util.find_spec(import_node.module)
    origin = getattr(spec, "origin", None) if spec is not None else None
    if not origin or origin in {"built-in", "frozen"}:
        return None
    target = Path(origin)
    return target if target.suffix == ".py" and target.exists() else None


def _merge_dict(base: Mapping[str, Any], override: Mapping[str, Any]) -> Dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, Mapping) and isinstance(merged.get(key), Mapping):
            merged[key] = _merge_dict(merged[key], value)
        else:
            merged[key] = value
    return merged


def _merge_feature_list(primary: List[Dict[str, Any]], incoming: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    merged: Dict[str, Dict[str, Any]] = {str(item.get("id")): dict(item) for item in primary if item.get("id")}
    for item in incoming:
        feature_id = str(item.get("id", "")).strip()
        if not feature_id:
            continue
        if feature_id in merged:
            merged[feature_id] = _merge_dict(merged[feature_id], item)
        else:
            merged[feature_id] = dict(item)
    return list(merged.values())


def _load_registry(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def load_registry(paths: Iterable[Path]) -> Dict[str, Any]:
    merged: Dict[str, Any] = {"features": [], "defaults": {}}
    for path in paths:
        data = _load_registry(path)
        if not data:
            continue
        imports = data.get("imports") or []
        if imports:
            import_paths = [(path.parent / Path(item)).resolve() for item in imports]
            data = _merge_dict(load_registry(import_paths), data)
        merged["defaults"] = _merge_dict(merged.get("defaults", {}), data.get("defaults", {}))
        merged["features"] = _merge_feature_list(list(merged.get("features", [])), list(data.get("features") or []))
    return merged


def _build_spec_from_features(
    *,
    features: Iterable[Dict[str, Any]],
    defaults: Mapping[str, Any],
    feature_ids: Optional[Iterable[str]],
    base_dir: Path,
) -> Dict[str, Any]:
    input_defaults = dict(defaults.get("inputs") or {})
    default_columns = dict(input_defaults.get("default_columns") or {})
    metric_overrides = dict(input_defaults.get("metric_overrides") or {})

    wanted = {str(fid) for fid in feature_ids} if feature_ids is not None else None
    output_features: List[Dict[str, Any]] = []

    for feature in features:
        feature_id = str(feature.get("id", "")).strip()
        if not feature_id or (wanted is not None and feature_id not in wanted):
            continue
        script = str(feature.get("script", "")).strip()
        if not script:
            continue
        script_path = Path(script)
        if not script_path.is_absolute():
            script_path = (base_dir / script_path).resolve()
        decorator_meta = load_decorator_metadata(script_path)
        decorator_defaults = decorator_meta.get("defaults") or {}

        params = _merge_dict(decorator_defaults.get("params", {}), feature.get("params", {}) or {})
        outputs = _merge_dict(decorator_defaults.get("outputs", {}), feature.get("outputs", {}) or {})
        raw_inputs = _merge_dict(decorator_defaults.get("inputs", {}), feature.get("inputs", {}) or {})

        inputs: Dict[str, Dict[str, Any]] = {}
        for name, raw_spec in (raw_inputs or {}).items():
            spec = dict(raw_spec or {})
            metric = spec.get("metric")
            if metric:
                column_defaults = dict(default_columns)
                column_defaults.update(metric_overrides.get(metric, {}) or {})
                for key, value in column_defaults.items():
                    spec.setdefault(key, value)
            inputs[name] = spec

        feature_entry: Dict[str, Any] = {"id": feature_id, "script": str(feature.get("script"))}
        if inputs:
            feature_entry["inputs"] = inputs
        if params:
            feature_entry["params"] = params
        if outputs:
            feature_entry["outputs"] = outputs
        output_features.append(feature_entry)

    return {"features": output_features}


def build_derived_spec_from_registry(
    *,
    registry_paths: Iterable[Path],
    feature_ids: Optional[Iterable[str]] = None,
    base_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    registry = load_registry(registry_paths)
    base_dir = base_dir or Path.cwd()
    return _build_spec_from_features(
        features=registry.get("features", []) or [],
        defaults=dict(registry.get("defaults") or {}),
        feature_ids=feature_ids,
        base_dir=base_dir,
    )


def scan_derived_feature_scripts(
    *,
    root: Path,
    include_globs: Optional[Iterable[str]] = None,
    exclude_globs: Optional[Iterable[str]] = None,
) -> List[Dict[str, Any]]:
    root = root.resolve()
    include_patterns = list(include_globs or ["**/*.py"])
    exclude_patterns = list(
        exclude_globs
        or [
            "**/__pycache__/**",
            "**/.venv/**",
            "**/venv/**",
            "**/.git/**",
            "**/_build/**",
            "**/build/**",
        ]
    )
    seen: Dict[str, Dict[str, Any]] = {}
    for pattern in include_patterns:
        for path in root.glob(pattern):
            if not path.is_file():
                continue
            rel_str = path.relative_to(root).as_posix()
            if any(fnmatch.fnmatch(rel_str, pat) for pat in exclude_patterns):
                continue
            decorator_meta = load_decorator_metadata(path)
            inline_meta, _ = parse_inline_metadata(path)
            if not decorator_meta.get("outputs") and not inline_meta and not decorator_meta.get("computation"):
                continue
            defaults = decorator_meta.get("defaults") or {}
            stem_id = path.stem
            if stem_id.endswith("_features"):
                stem_id = stem_id[: -len("_features")]
            feature_id = str(
                defaults.get("feature_id")
                or decorator_meta.get("feature_id")
                or stem_id
                or decorator_meta.get("computation", {}).get("id")
                or path.stem
            )
            try:
                rel_script = path.relative_to(root).as_posix()
            except ValueError:
                try:
                    rel_script = Path(os.path.relpath(path.resolve(), Path.cwd())).as_posix()
                except Exception:
                    rel_script = str(path)
            entry = {"id": feature_id, "script": rel_script}
            if defaults.get("inputs"):
                entry["inputs"] = dict(defaults.get("inputs") or {})
            if defaults.get("params"):
                entry["params"] = dict(defaults.get("params") or {})
            if defaults.get("outputs"):
                entry["outputs"] = dict(defaults.get("outputs") or {})
            seen[feature_id] = entry
    return list(seen.values())


def build_derived_spec_from_data_book(
    *,
    root: Path,
    registry_paths: Optional[Iterable[Path]] = None,
    include_globs: Optional[Iterable[str]] = None,
    exclude_globs: Optional[Iterable[str]] = None,
    feature_ids: Optional[Iterable[str]] = None,
) -> Dict[str, Any]:
    scan_features = scan_derived_feature_scripts(
        root=root,
        include_globs=include_globs,
        exclude_globs=exclude_globs,
    )
    defaults: Dict[str, Any] = {}
    registry_features: List[Dict[str, Any]] = []
    if registry_paths:
        registry = load_registry(registry_paths)
        defaults = dict(registry.get("defaults") or {})
        registry_features = list(registry.get("features") or [])

    merged_features = _merge_feature_list(scan_features, registry_features)
    return _build_spec_from_features(
        features=merged_features,
        defaults=defaults,
        feature_ids=feature_ids,
        base_dir=root,
    )


def build_derived_spec_from_root(
    *,
    root: Path,
    registry_paths: Optional[Iterable[Path]] = None,
    include_globs: Optional[Iterable[str]] = None,
    exclude_globs: Optional[Iterable[str]] = None,
    feature_ids: Optional[Iterable[str]] = None,
) -> Dict[str, Any]:
    return build_derived_spec_from_data_book(
        root=root,
        registry_paths=registry_paths,
        include_globs=include_globs,
        exclude_globs=exclude_globs,
        feature_ids=feature_ids,
    )


__all__ = [
    "load_registry",
    "load_decorator_metadata",
    "build_derived_spec_from_registry",
    "scan_derived_feature_scripts",
    "build_derived_spec_from_data_book",
    "build_derived_spec_from_root",
]
