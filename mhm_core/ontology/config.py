"""Ontology integration configuration helpers."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

import yaml


@dataclass
class UnificationFeature:
    feature_id: str
    odim_feature: str
    category: str
    method: str
    output_column: str
    inputs: object
    params: Dict[str, object]
    selection: Dict[str, object]
    computation: Dict[str, object]
    dimensions: List[str]
    unify: bool


@dataclass
class UnificationSpec:
    features: List[UnificationFeature]


def _load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def load_metric_mapping(path: Path) -> dict:
    return _load_yaml(path)


def load_unification_spec(path: Path, *, odim_namespace: str | None = None) -> UnificationSpec:
    if path.suffix.lower() == ".owl":
        from .catalog import load_unification_catalog

        raw_features = []
        for entry in load_unification_catalog([path], odim_namespace=odim_namespace):
            inputs = []
            for spec in entry.inputs:
                input_spec: Dict[str, object] = {}
                if spec.metric:
                    input_spec["metric"] = spec.metric
                if spec.time_column:
                    input_spec["time_column"] = spec.time_column
                if spec.value_column:
                    input_spec["value_column"] = spec.value_column
                if spec.start_column:
                    input_spec["start_column"] = spec.start_column
                if spec.end_column:
                    input_spec["end_column"] = spec.end_column
                if spec.unlock_duration_column:
                    input_spec["unlock_duration_column"] = spec.unlock_duration_column
                if spec.unlock_count_column:
                    input_spec["unlock_count_column"] = spec.unlock_count_column
                if spec.state_column:
                    input_spec["state_column"] = spec.state_column
                if spec.priority is not None:
                    input_spec["priority"] = spec.priority
                if spec.source_metric:
                    input_spec["source_metric"] = spec.source_metric
                if spec.path:
                    input_spec["path"] = spec.path
                if spec.segment_column:
                    input_spec["segment_column"] = spec.segment_column
                if spec.sensor:
                    input_spec["sensor"] = spec.sensor
                if spec.provider:
                    input_spec["provider"] = spec.provider
                if spec.feature:
                    input_spec["feature"] = spec.feature
                if spec.label:
                    input_spec["label"] = spec.label
                if spec.rapids_dir:
                    input_spec["rapids_dir"] = spec.rapids_dir
                if spec.cumulative is not None:
                    input_spec["cumulative"] = spec.cumulative
                inputs.append(input_spec)
            raw_features.append(
                {
                    "id": entry.unification_id,
                    "odim_feature": entry.odim_feature,
                    "category": "",
                    "method": entry.method,
                    "output_column": entry.output_column,
                    "inputs": inputs,
                    "selection": entry.selection,
                    "params": entry.params,
                }
            )
    else:
        data = _load_yaml(path)
        raw_features = data.get("features", []) or []
    features: List[UnificationFeature] = []
    for raw in raw_features:
        feature_id = str(raw.get("id", "")).strip()
        if not feature_id:
            raise ValueError("Unification feature missing id")
        features.append(
            UnificationFeature(
                feature_id=feature_id,
                odim_feature=str(raw.get("odim_feature", "odim:DerivedFeature")).strip(),
                category=str(raw.get("category", "")).strip(),
                method=str(raw.get("method", "daily_sum")).strip(),
                output_column=str(raw.get("output_column", feature_id)).strip(),
                inputs=raw.get("inputs"),
                params=dict(raw.get("params") or {}),
                selection=dict(raw.get("selection") or {}),
                computation=dict(raw.get("computation") or {}),
                dimensions=[str(dim) for dim in (raw.get("dimensions") or [])],
                unify=bool(raw.get("unify", True)),
            )
        )
    return UnificationSpec(features=features)


def select_features(
    spec: UnificationSpec,
    *,
    categories: Optional[List[str]] = None,
    feature_ids: Optional[List[str]] = None,
) -> List[UnificationFeature]:
    if feature_ids:
        wanted = {str(fid).strip() for fid in feature_ids if str(fid).strip()}
        return [feat for feat in spec.features if feat.feature_id in wanted]
    if categories:
        wanted = {str(cat).strip() for cat in categories if str(cat).strip()}
        return [feat for feat in spec.features if feat.category in wanted]
    return list(spec.features)


def write_feature_plan(
    path: Path,
    *,
    mapping_path: Optional[str],
    unification_path: object,
    selected: List[UnificationFeature],
    request: Mapping[str, Any],
) -> None:
    payload = {
        "mapping": mapping_path,
        "unification": unification_path,
        "request": dict(request),
        "features": [
            {
                "id": feat.feature_id,
                "odim_feature": feat.odim_feature,
                "category": feat.category,
                "method": feat.method,
                "output_column": feat.output_column,
                "inputs": feat.inputs,
                "params": feat.params,
                "selection": feat.selection,
                "computation": feat.computation,
                "dimensions": feat.dimensions,
                "unify": feat.unify,
            }
            for feat in selected
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


__all__ = [
    "UnificationSpec",
    "UnificationFeature",
    "load_metric_mapping",
    "load_unification_spec",
    "select_features",
    "write_feature_plan",
]
