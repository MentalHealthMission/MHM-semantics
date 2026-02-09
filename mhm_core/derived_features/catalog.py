"""Derived feature catalog helpers."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional
import re

from .registry import load_decorator_metadata
from .inline_metadata import parse_inline_metadata, resolve_inline


def _slugify(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "_", value.strip()).strip("_").lower()


def _output_filename(feature_id: str, output_key: str, outputs_map: Mapping[str, str]) -> str:
    if output_key in outputs_map:
        return str(outputs_map[output_key])
    if output_key == "default":
        return f"{feature_id}.csv"
    return f"{feature_id}_{output_key}.csv"


def _expand_outputs(
    meta_outputs: List[Mapping[str, Any]],
    params: Mapping[str, Any],
) -> List[Dict[str, Any]]:
    expanded: List[Dict[str, Any]] = []
    for item in meta_outputs:
        item_dict = dict(item)
        pattern = item_dict.pop("pattern", None)
        if pattern:
            segment_param = str(item_dict.get("segment_param", "segments"))
            segment_key = str(item_dict.get("segment_key", "name"))
            segments = list(params.get(segment_param) or [])
            if not segments:
                segments = list(item_dict.get("default_segments") or [])
            for seg in segments:
                name = str(seg.get(segment_key, "")).strip()
                if not name:
                    continue
                out = dict(item_dict)
                out["column"] = pattern.format(segment=name)
                out["segment"] = name
                expanded.append(out)
        else:
            expanded.append(item_dict)
    return expanded


def build_catalog(
    derived_spec: Mapping[str, Any],
    *,
    base_dir: Path,
) -> List[Dict[str, Any]]:
    catalog: List[Dict[str, Any]] = []
    for feature in derived_spec.get("features", []) or []:
        feature_id = str(feature.get("id", "")).strip()
        if not feature_id:
            continue
        script_path = Path(str(feature.get("script", "")))
        if not script_path.is_absolute():
            script_path = (base_dir / script_path).resolve()
        decorator_meta = load_decorator_metadata(script_path)
        inline_meta, inline_computation = parse_inline_metadata(script_path)
        if not inline_meta and not decorator_meta.get("outputs"):
            continue

        outputs_map = dict(feature.get("outputs") or {})
        params = dict(feature.get("params") or {})
        if decorator_meta.get("outputs"):
            meta_outputs = _expand_outputs(list(decorator_meta.get("outputs") or []), params=params)
        else:
            meta_outputs = [
                {
                    "column": column,
                    "odim_feature": meta.get("odim_feature"),
                    "category": meta.get("category"),
                    "doc": meta.get("doc"),
                }
                for column, meta in inline_meta.items()
            ]

        for meta in meta_outputs:
            output_key = str(meta.get("output", "default"))
            output_file = _output_filename(feature_id, output_key, outputs_map)
            column = meta.get("column")
            resolved = resolve_inline(inline_meta, column) if column else None
            odim_feature = resolved.get("odim_feature") if resolved else meta.get("odim_feature")
            category = resolved.get("category") if resolved and resolved.get("category") else meta.get("category", "")
            doc = resolved.get("doc") if resolved else meta.get("doc")
            catalog.append(
                {
                    "feature_id": feature_id,
                    "script": str(feature.get("script")),
                    "output": output_key,
                    "file": output_file,
                    "column": column,
                    "odim_feature": odim_feature,
                    "category": category,
                    "doc": doc,
                    "dimensions": list(meta.get("dimensions") or []),
                    "platforms": list(meta.get("platforms") or []),
                    "unify": bool(meta.get("unify", len(meta.get("dimensions") or []) == 0)),
                    "segment_column": meta.get("segment_column", "segment_date"),
                    "computation": meta.get("computation")
                    or inline_computation
                    or decorator_meta.get("computation")
                    or {},
                }
            )
    return catalog


def build_unification(
    catalog: List[Dict[str, Any]],
    *,
    path_template: str,
) -> dict:
    features: List[Dict[str, Any]] = []
    for entry in catalog:
        column = entry.get("column")
        if not column:
            continue
        feature_id = f"{entry['feature_id']}_{_slugify(str(column))}"
        path = path_template.format(
            file=entry["file"],
            participant_id="{participant_id}",
            workspace_dir="{workspace_dir}",
        )
        features.append(
            {
                "id": feature_id,
                "odim_feature": entry.get("odim_feature") or "odim:DerivedFeature",
                "category": entry.get("category", ""),
                "method": "column",
                "output_column": column,
                "dimensions": entry.get("dimensions") or [],
                "unify": bool(entry.get("unify", True)),
                "inputs": [
                    {
                        "name": "derived",
                        "path": path,
                        "value_column": column,
                        "segment_column": entry.get("segment_column", "segment_date"),
                        "source_metric": f"derived:{entry['feature_id']}",
                        "priority": 1,
                    }
                ],
                "computation": entry.get("computation") or {},
            }
        )
    return {"features": features}


__all__ = ["build_catalog", "build_unification"]
