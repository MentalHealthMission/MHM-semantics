"""Build CONNECT run specs from ontology targets."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional, Set
import re

import yaml

from .catalog import load_metric_catalog as load_metric_catalog_owl, load_unification_catalog
from .preference import normalize_source_preference, source_type_from_method

@dataclass
class UnificationEntry:
    feature_id: str
    odim_feature: str
    category: str
    method: str
    output_column: str
    inputs: object
    source_path: str


@dataclass
class RapidsNeed:
    sensor: str
    provider: str
    feature: str
    label: str
    priority: int


@dataclass
class SpecPlan:
    metrics: Set[str] = field(default_factory=set)
    derived_feature_ids: Set[str] = field(default_factory=set)
    rapids_needs: List[RapidsNeed] = field(default_factory=list)
    unification_feature_ids: Set[str] = field(default_factory=set)
    unification_specs: Set[str] = field(default_factory=set)
    phenotype_rules: Set[str] = field(default_factory=set)
    needs_unify: bool = False
    needs_reason: bool = False


def _load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _parse_unification_specs(paths: Iterable[Path]) -> List[UnificationEntry]:
    entries: List[UnificationEntry] = []
    for path in paths:
        data = _load_yaml(path)
        for raw in data.get("features", []) or []:
            feature_id = str(raw.get("id", "")).strip()
            if not feature_id:
                continue
            entries.append(
                UnificationEntry(
                    feature_id=feature_id,
                    odim_feature=str(raw.get("odim_feature", "odim:DerivedFeature")).strip(),
                    category=str(raw.get("category", "")).strip(),
                    method=str(raw.get("method", "daily_sum")).strip(),
                    output_column=str(raw.get("output_column", feature_id)).strip(),
                    inputs=raw.get("inputs"),
                    source_path=str(path),
                )
            )
    return entries


def _iter_input_specs(inputs: object) -> List[Mapping[str, object]]:
    if isinstance(inputs, list):
        return [spec for spec in inputs if isinstance(spec, Mapping)]
    if isinstance(inputs, Mapping):
        return [inputs]
    return []


def _collect_metric_names(input_specs: List[Mapping[str, object]]) -> Set[str]:
    metrics: Set[str] = set()
    for spec in input_specs:
        metric = spec.get("metric")
        if metric:
            metrics.add(str(metric))
    return metrics


def _collect_derived_ids(input_specs: List[Mapping[str, object]]) -> Set[str]:
    derived_ids: Set[str] = set()
    for spec in input_specs:
        source_metric = spec.get("source_metric")
        if not source_metric:
            continue
        metric = str(source_metric)
        if metric.startswith("derived:"):
            derived_ids.add(metric.split(":", 1)[1])
    return derived_ids


def _collect_rapids_needs(input_specs: List[Mapping[str, object]]) -> List[RapidsNeed]:
    needs: List[RapidsNeed] = []
    for spec in input_specs:
        sensor = spec.get("sensor")
        feature = spec.get("feature")
        if not sensor or not feature:
            continue
        needs.append(
            RapidsNeed(
                sensor=str(sensor),
                provider=str(spec.get("provider", "RAPIDS")),
                feature=str(feature),
                label=str(spec.get("label", "")),
                priority=int(spec.get("priority", 999)),
            )
        )
    return needs


def _load_metric_catalog(path: Path) -> Dict[str, Dict[str, object]]:
    data = _load_yaml(path)
    return {str(k): dict(v or {}) for k, v in (data.get("measurements") or {}).items()}


def _load_derived_catalog(path: Path) -> List[Dict[str, object]]:
    data = _load_yaml(path)
    return list(data.get("derived_features") or [])


def _load_derived_specs(paths: Iterable[Path]) -> Dict[str, Dict[str, object]]:
    features: Dict[str, Dict[str, object]] = {}
    for path in paths:
        data = _load_yaml(path)
        for raw in data.get("features", []) or []:
            feature_id = str(raw.get("id", "")).strip()
            if not feature_id:
                continue
            features[feature_id] = dict(raw)
    return features


def _load_phenotype_catalog(path: Path) -> Dict[str, Dict[str, object]]:
    data = _load_yaml(path)
    return {str(k): dict(v or {}) for k, v in (data.get("phenotypes") or {}).items()}


def _load_disruptive_classes(path: Path) -> List[str]:
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    entries: List[str] = []
    for block in text.split("<owl:Class"):
        if "isDisruptive" not in block:
            continue
        if "true" not in block:
            continue
        match = re.search(r'rdf:about="[^#]+#([^"]+)"', block)
        if match:
            entries.append(f"odim:{match.group(1)}")
    return entries


def build_plan(
    *,
    targets: List[str],
    metrics: List[str],
    prefer: List[str],
    derived_catalog_path: Path,
    derived_spec_paths: List[Path],
    unification_paths: List[Path],
    phenotype_catalog_path: Path,
    metric_catalog_path: Optional[Path] = None,
    ontology_paths: Optional[List[Path]] = None,
    disruptive_ontology_path: Optional[Path] = None,
) -> SpecPlan:
    plan = SpecPlan()
    metric_catalog: Dict[str, Dict[str, object]] = {}
    category_to_metrics: Dict[str, Set[str]] = {}
    odim_unification_from_ontology: Dict[str, List[UnificationEntry]] = {}
    category_to_unification: Dict[str, List[UnificationEntry]] = {}

    if ontology_paths:
        metric_catalog = load_metric_catalog_owl(ontology_paths)
        raw_unification = load_unification_catalog(ontology_paths)
        for entry in raw_unification:
            odim_feature = entry.odim_feature or ""
            if not odim_feature:
                continue
            inputs: List[Dict[str, object]] = []
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

            uni_entry = UnificationEntry(
                feature_id=entry.unification_id,
                odim_feature=odim_feature,
                category="",
                method=entry.method or "",
                output_column=entry.output_column or entry.unification_id,
                inputs=inputs,
                source_path="ontology",
            )
            odim_unification_from_ontology.setdefault(odim_feature, []).append(uni_entry)
            for cat in entry.categories:
                category_to_unification.setdefault(cat, []).append(uni_entry)

    if metric_catalog_path and metric_catalog_path.exists():
        metric_catalog = _load_metric_catalog(metric_catalog_path)

    for metric_id, meta in metric_catalog.items():
        cats = meta.get("categories") or []
        for cat in cats:
            category_to_metrics.setdefault(cat, set()).add(metric_id)

    derived_catalog = _load_derived_catalog(derived_catalog_path)
    derived_specs = _load_derived_specs(derived_spec_paths)
    phenotypes = _load_phenotype_catalog(phenotype_catalog_path)
    unification_entries = _parse_unification_specs(unification_paths)

    odim_to_unification: Dict[str, List[UnificationEntry]] = {}
    id_to_unification: Dict[str, UnificationEntry] = {}
    for entry in unification_entries:
        odim_to_unification.setdefault(entry.odim_feature, []).append(entry)
        id_to_unification[entry.feature_id] = entry
    if odim_unification_from_ontology:
        odim_to_unification = odim_unification_from_ontology
        id_to_unification.clear()
        for entries in odim_unification_from_ontology.values():
            for entry in entries:
                id_to_unification[entry.feature_id] = entry

    odim_to_derived: Dict[str, Set[str]] = {}
    for entry in derived_catalog:
        odim_feature = str(entry.get("odim_feature") or "").strip()
        feature_id = str(entry.get("feature_id") or "").strip()
        if odim_feature and feature_id:
            odim_to_derived.setdefault(odim_feature, set()).add(feature_id)

    disruptive_classes: List[str] = []
    if disruptive_ontology_path:
        disruptive_classes = _load_disruptive_classes(disruptive_ontology_path)

    return apply_targets(
        plan,
        targets=targets,
        metrics=metrics,
        prefer=prefer,
        metric_catalog=metric_catalog,
        category_to_metrics=category_to_metrics,
        category_to_unification=category_to_unification,
        odim_to_unification=odim_to_unification,
        id_to_unification=id_to_unification,
        odim_to_derived=odim_to_derived,
        derived_specs=derived_specs,
        phenotypes=phenotypes,
        disruptive_classes=disruptive_classes,
    )

def apply_targets(
    plan: SpecPlan,
    *,
    targets: List[str],
    metrics: List[str],
    prefer: List[str],
    metric_catalog: Dict[str, Dict[str, object]],
    category_to_metrics: Dict[str, Set[str]],
    category_to_unification: Dict[str, List[UnificationEntry]],
    odim_to_unification: Dict[str, List[UnificationEntry]],
    id_to_unification: Dict[str, UnificationEntry],
    odim_to_derived: Dict[str, Set[str]],
    derived_specs: Dict[str, Dict[str, object]],
    phenotypes: Dict[str, Dict[str, object]],
    disruptive_classes: List[str],
) -> SpecPlan:
    source_preference = normalize_source_preference(prefer)

    def resolve_unification_entry(entry: UnificationEntry) -> None:
        plan.unification_feature_ids.add(entry.feature_id)
        plan.unification_specs.add(entry.source_path)
        input_specs = _iter_input_specs(entry.inputs)
        source_type = source_type_from_method(entry.method, entry.inputs)
        if source_type == "derived":
            plan.derived_feature_ids.update(_collect_derived_ids(input_specs))
        elif source_type == "rapids":
            plan.rapids_needs.extend(_collect_rapids_needs(input_specs))
        plan.metrics.update(_collect_metric_names(input_specs))

    def resolve_odim_feature(odim_feature: str) -> None:
        candidates = odim_to_unification.get(odim_feature, [])
        if not candidates:
            for feature_id in odim_to_derived.get(odim_feature, set()):
                plan.derived_feature_ids.add(feature_id)
            return
        resolved_candidates: List[UnificationEntry] = []
        for cand in candidates:
            if cand.feature_id in id_to_unification:
                resolved_candidates.append(id_to_unification[cand.feature_id])
            else:
                resolved_candidates.append(cand)
        for pref in source_preference:
            chosen = [
                cand
                for cand in resolved_candidates
                if source_type_from_method(cand.method, cand.inputs) == pref
            ]
            if chosen:
                for entry in chosen:
                    resolve_unification_entry(entry)
                break

    def resolve_target(target: str) -> None:
        if target in metric_catalog:
            plan.metrics.add(target)
            return
        if target in category_to_metrics or target in category_to_unification:
            if target in category_to_metrics:
                plan.metrics.update(category_to_metrics[target])
            if target in category_to_unification:
                plan.needs_unify = True
                for entry in category_to_unification[target]:
                    resolve_unification_entry(entry)
            return
        if target in id_to_unification:
            resolve_unification_entry(id_to_unification[target])
            plan.needs_unify = True
            return
        if target.startswith("odim:"):
            if target in phenotypes:
                plan.needs_unify = True
                plan.needs_reason = True
                rule_info = phenotypes[target]
                rule_path = str(rule_info.get("rule", "")).strip()
                if rule_path:
                    plan.phenotype_rules.add(rule_path)
                deps = list(rule_info.get("depends_on") or [])
                if not deps and disruptive_classes:
                    deps = disruptive_classes
                for dep in deps:
                    dep_str = str(dep)
                    if dep_str in phenotypes:
                        resolve_target(dep_str)
                    else:
                        resolve_odim_feature(dep_str)
            else:
                plan.needs_unify = True
                resolve_odim_feature(target)
            return
        raise ValueError(f"Unknown target: {target}")

    for metric in metrics:
        plan.metrics.add(metric)

    for target in targets:
        resolve_target(target)

    for feature_id in sorted(plan.derived_feature_ids):
        feature = derived_specs.get(feature_id)
        if not feature:
            continue
        inputs = feature.get("inputs") or []
        specs: Iterable[object]
        if isinstance(inputs, Mapping):
            specs = inputs.values()
        else:
            specs = inputs
        for spec in specs:
            if not isinstance(spec, Mapping):
                continue
            metric = spec.get("metric")
            if metric:
                plan.metrics.add(str(metric))

    return plan


def build_rapids_step(
    *,
    plan: SpecPlan,
    template_spec_path: Optional[Path] = None,
    inputs_map: Optional[Dict[str, Dict[str, str]]] = None,
    fitbit_inputs: Optional[Dict[str, str]] = None,
) -> Optional[Dict[str, object]]:
    if not plan.rapids_needs:
        return None
    rapids_step: Dict[str, object] = {"type": "rapids"}
    if template_spec_path:
        template = _load_yaml(template_spec_path)
        found = False
        for step in template.get("processing", {}).get("steps", []):
            if step.get("type") == "rapids":
                rapids_step = dict(step)
                found = True
                break
        if not found:
            raise ValueError("Rapids template missing rapids step")

    inputs_map = dict(inputs_map or rapids_step.get("inputs") or {})
    fitbit_inputs = dict(fitbit_inputs or rapids_step.get("fitbit_inputs") or {})
    if not inputs_map and not fitbit_inputs:
        raise ValueError("Rapids inputs are required (template or ontology mapping)")

    features: Dict[str, Dict[str, object]] = {}
    needed_metrics: Set[str] = set()
    seen_features: Set[tuple[str, str, str]] = set()

    for need in plan.rapids_needs:
        sensor = need.sensor
        provider = need.provider
        feature = need.feature
        if sensor.startswith("FITBIT_"):
            metric = fitbit_inputs.get(sensor)
            if metric:
                needed_metrics.add(str(metric))
        else:
            mapping = inputs_map.get(sensor, {})
            label = need.label.lower()
            if "ios" in label:
                metric = mapping.get("IOS")
                if metric:
                    needed_metrics.add(str(metric))
            elif "android" in label:
                metric = mapping.get("ANDROID")
                if metric:
                    needed_metrics.add(str(metric))
            else:
                for metric in mapping.values():
                    if metric:
                        needed_metrics.add(str(metric))

        sensor_features = features.setdefault(sensor, {"providers": {}})
        provider_block = sensor_features["providers"].setdefault(provider, {"features": []})
        feature_key = (sensor, provider, feature)
        if feature_key not in seen_features:
            provider_block["features"].append(feature)
            seen_features.add(feature_key)

    plan.metrics.update(needed_metrics)

    rapids_step["inputs"] = {k: v for k, v in inputs_map.items() if k in features}
    rapids_step["fitbit_inputs"] = {k: v for k, v in fitbit_inputs.items() if k in features}
    rapids_step["features"] = features
    return rapids_step


def build_derived_spec(
    *,
    plan: SpecPlan,
    derived_spec_paths: List[Path],
    output_path: Path,
) -> Optional[Path]:
    if not plan.derived_feature_ids:
        return None
    all_features = _load_derived_specs(derived_spec_paths)
    selected = [all_features[fid] for fid in sorted(plan.derived_feature_ids) if fid in all_features]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(yaml.safe_dump({"features": selected}, sort_keys=False), encoding="utf-8")
    return output_path


def build_run_spec(
    *,
    plan: SpecPlan,
    run_id: str,
    created_by: str,
    created_at: str,
    source_bucket: str,
    source_prefix: str,
    discover_all: bool,
    participants: List[str],
    sites: List[str],
    workspace_root: str,
    run_subdir: str,
    outputs: Mapping[str, str],
    redact_rules: List[Mapping[str, object]],
    derived_spec_path: Optional[Path],
    rapids_template_path: Optional[Path],
    rapids_inputs: Optional[Dict[str, Dict[str, str]]] = None,
    rapids_fitbit_inputs: Optional[Dict[str, str]] = None,
    unification_paths: List[Path],
    ontology_mapping_path: Path,
    ontology_files: List[str],
    rules_dir: Optional[str] = None,
    include_ontology_steps: bool = True,
    source_preference: Optional[List[str]] = None,
) -> dict:
    steps: List[Dict[str, object]] = [
        {"type": "download", "update": True},
        {"type": "merge", "output_format": "csv", "update": True},
        {"type": "redact", "rules": redact_rules},
    ]

    if rapids_template_path or rapids_inputs or rapids_fitbit_inputs:
        rapids_step = build_rapids_step(
            plan=plan,
            template_spec_path=rapids_template_path,
            inputs_map=rapids_inputs,
            fitbit_inputs=rapids_fitbit_inputs,
        )
        if rapids_step:
            rapids_step["staging_dir"] = f"{workspace_root}/{run_subdir}/rapids/{{platform}}"
            steps.append(rapids_step)

    if derived_spec_path:
        steps.append(
            {
                "type": "derived_features",
                "spec": str(derived_spec_path),
                "output_dir": f"{workspace_root}/{run_subdir}/derived_features",
            }
        )

    if include_ontology_steps and plan.needs_unify:
        prefer_order = normalize_source_preference(source_preference)
        spec_paths = [str(path) for path in unification_paths]
        if plan.unification_specs:
            if plan.unification_specs == {"ontology"}:
                spec_paths = [str(ontology_mapping_path)]
            else:
                spec_paths = sorted(plan.unification_specs)
        steps.append(
            {
                "type": "ontology_select",
                "mapping": str(ontology_mapping_path),
                "unification_spec": spec_paths,
                "request": {
                    "features": sorted(plan.unification_feature_ids),
                    "prefer": prefer_order,
                },
                "output_plan": f"{workspace_root}/{run_subdir}/ontology/feature-plan.yaml",
            }
        )
        steps.append(
            {
                "type": "ontology_unify",
                "plan": f"{workspace_root}/{run_subdir}/ontology/feature-plan.yaml",
                "output_dir": f"{workspace_root}/{run_subdir}/ontology/unified",
            }
        )

    if include_ontology_steps and plan.needs_reason:
        def _rule_sort_key(path: str) -> tuple[int, str]:
            name = Path(path).name
            return (0 if "evidence" in name else 1, name)

        reason_step: Dict[str, object] = {
            "type": "ontology_reason",
            "plan": f"{workspace_root}/{run_subdir}/ontology/feature-plan.yaml",
            "mapping": str(ontology_mapping_path),
            "unified_dir": f"{workspace_root}/{run_subdir}/ontology/unified",
            "output_dir": f"{workspace_root}/{run_subdir}/ontology/reasoned",
            "rules": sorted(plan.phenotype_rules, key=_rule_sort_key),
            "ontology_files": ontology_files,
            "trace": True,
            "trace_summary": True,
            "trace_max_paths": 3,
        }
        if rules_dir:
            reason_step["rules_dir"] = rules_dir
        steps.append(reason_step)

    return {
        "run_id": run_id,
        "created_by": created_by,
        "created_at": created_at,
        "source": {
            "bucket": source_bucket,
            "prefix": source_prefix,
            "participants": participants,
            "discover_all": discover_all,
            "sites": sites,
        },
        "filters": {"include_metrics": sorted(plan.metrics)},
        "workspace": {"root": workspace_root, "run_subdir": run_subdir},
        "outputs": dict(outputs),
        "processing": {"steps": steps},
    }
