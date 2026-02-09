"""Ontology reasoning utilities."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, Mapping, Optional

import pandas as pd

import yaml
from rdflib import Graph, Literal, Namespace, RDF, URIRef
from rdflib.namespace import RDFS, XSD
import re


ODIM = Namespace("http://connectdigitalstudy.com/ontology#")
PROV = Namespace("http://www.w3.org/ns/prov#")


@dataclass
class FeaturePlanEntry:
    feature_id: str
    odim_feature: str
    output_column: str
    computation: Dict[str, object]


def _load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _resolve_curie(value: str) -> URIRef:
    if value.startswith("http://") or value.startswith("https://"):
        return URIRef(value)
    if value.startswith("odim:"):
        return ODIM[value.split(":", 1)[1]]
    return ODIM[value]


def load_feature_plan(path: Path) -> list[FeaturePlanEntry]:
    data = _load_yaml(path)
    features = []
    for raw in data.get("features", []):
        feature_id = str(raw.get("id", "")).strip()
        if not feature_id:
            continue
        features.append(
            FeaturePlanEntry(
                feature_id=feature_id,
                odim_feature=str(raw.get("odim_feature", "odim:DerivedFeature")),
                output_column=str(raw.get("output_column", feature_id)),
                computation=dict(raw.get("computation") or {}),
            )
        )
    return features


def load_metric_mapping(path: Optional[Path]) -> Dict[str, Dict[str, object]]:
    if not path or not path.exists():
        return {}
    if path.suffix.lower() == ".owl":
        from .catalog import load_metric_catalog

        return load_metric_catalog([path])
    data = _load_yaml(path)
    return {str(k): dict(v or {}) for k, v in (data.get("measurements") or {}).items()}


def build_graph(
    *,
    participant_id: str,
    unified: pd.DataFrame,
    feature_plan: Iterable[FeaturePlanEntry],
    metric_mapping: Mapping[str, Mapping[str, object]],
    ontology_paths: Optional[Iterable[Path]] = None,
) -> Graph:
    graph = Graph()
    graph.bind("odim", ODIM)
    if ontology_paths:
        for path in ontology_paths:
            if path and path.exists():
                graph.parse(path)

    participant_uri = ODIM[f"Participant_{participant_id}"]
    graph.add((participant_uri, RDF.type, ODIM.Participant))

    feature_map = {feat.feature_id: feat for feat in feature_plan}
    metric_nodes: Dict[str, URIRef] = {}

    for _, row in unified.iterrows():
        date = row.get("segment_date")
        if not date:
            continue
        date_literal = Literal(str(date), datatype=XSD.date)
        for feature_id, feat in feature_map.items():
            value = row.get(feat.output_column)
            if pd.isna(value):
                continue
            feature_uri = ODIM[f"Feature_{feature_id}_{participant_id}_{date}"]
            graph.add((feature_uri, RDF.type, _resolve_curie(feat.odim_feature)))
            graph.add((feature_uri, ODIM.hasValue, Literal(float(value))))
            graph.add((feature_uri, ODIM.resultTime, date_literal))
            graph.add((feature_uri, ODIM.featureOfInterest, participant_uri))

            source_col = f"{feature_id}_source"
            source_metric = row.get(source_col)
            if isinstance(source_metric, str) and source_metric:
                metric_uri = metric_nodes.get(source_metric)
                if metric_uri is None:
                    metric_uri = ODIM[f"Measurement_{source_metric}_{participant_id}_{date}"]
                    metric_nodes[source_metric] = metric_uri
                    graph.add((metric_uri, RDF.type, ODIM.Measurement))
                    graph.add((metric_uri, ODIM.resultTime, date_literal))
                    graph.add((metric_uri, ODIM.featureOfInterest, participant_uri))
                    mapping = metric_mapping.get(source_metric, {})
                    observed = mapping.get("observed_property")
                    if observed:
                        graph.add((metric_uri, ODIM.observedProperty, _resolve_curie(str(observed))))
                graph.add((feature_uri, ODIM.wasDerivedFrom, metric_uri))

            comp_spec = feat.computation or {}
            if comp_spec:
                comp_id = str(comp_spec.get("id") or feature_id)
                comp_type = str(comp_spec.get("type") or "odim:Computation")
                comp_label = comp_spec.get("label")
                comp_uri = ODIM[f"Computation_{comp_id}_{participant_id}_{date}"]
                graph.add((comp_uri, RDF.type, _resolve_curie(comp_type)))
                if comp_label:
                    graph.add((comp_uri, RDFS.label, Literal(str(comp_label))))
                graph.add((feature_uri, ODIM.wasComputedBy, comp_uri))
                uses = comp_spec.get("uses") or []
                for used in uses:
                    metric_name = None
                    if isinstance(used, str):
                        metric_name = used
                    elif isinstance(used, Mapping):
                        metric_name = used.get("metric") or used.get("id")
                    if not metric_name:
                        continue
                    metric_name = str(metric_name)
                    metric_uri = metric_nodes.get(metric_name)
                    if metric_uri is None:
                        metric_uri = ODIM[f"Measurement_{metric_name}_{participant_id}_{date}"]
                        metric_nodes[metric_name] = metric_uri
                        graph.add((metric_uri, RDF.type, ODIM.Measurement))
                        graph.add((metric_uri, ODIM.resultTime, date_literal))
                        graph.add((metric_uri, ODIM.featureOfInterest, participant_uri))
                        mapping = metric_mapping.get(metric_name, {})
                        observed = mapping.get("observed_property")
                        if observed:
                            graph.add((metric_uri, ODIM.observedProperty, _resolve_curie(str(observed))))
                    graph.add((comp_uri, PROV.used, metric_uri))

    return graph


def apply_rules(
    *,
    graph: Graph,
    rule_path: Path,
    tokens: Mapping[str, object],
) -> Graph:
    rule_text = rule_path.read_text(encoding="utf-8")
    tokens = dict(tokens or {})
    for key, value in tokens.items():
        rule_text = rule_text.replace(f"{{{key}}}", str(value))

    def _format_token(value: object) -> str:
        if value is None:
            return ""
        return str(value)

    def _apply_values_overrides(text: str) -> str:
        values_re = re.compile(r"VALUES\\s*\\(([^)]*)\\)\\s*\\{([^}]*)\\}", re.IGNORECASE | re.DOTALL)

        def replace_block(match: re.Match[str]) -> str:
            vars_raw = match.group(1)
            body = match.group(2)
            var_names = [item.strip().lstrip("?") for item in vars_raw.split() if item.strip()]
            if not var_names:
                return match.group(0)
            tuple_re = re.compile(r"\\(([^)]*)\\)")

            def replace_tuple(tmatch: re.Match[str]) -> str:
                values = tmatch.group(1).strip().split()
                if not values:
                    return tmatch.group(0)
                for idx, var_name in enumerate(var_names):
                    if var_name in tokens and idx < len(values):
                        values[idx] = _format_token(tokens[var_name])
                return "(" + " ".join(values) + ")"

            return f"VALUES ({vars_raw}) {{{tuple_re.sub(replace_tuple, body)}}}"

        return values_re.sub(replace_block, text)

    if tokens:
        rule_text = _apply_values_overrides(rule_text)
    result = graph.query(rule_text)
    constructed = getattr(result, "graph", None)
    if constructed is None:
        return graph
    graph += constructed
    return graph


def _curie_name(value: URIRef) -> str:
    text = str(value)
    if text.startswith(str(ODIM)):
        return text.split("#", 1)[-1]
    return text


def _is_phenotype_node(node: URIRef) -> bool:
    return str(node).startswith(f"{ODIM}Phenotype_")


def inferred_phenotypes(graph: Graph) -> pd.DataFrame:
    rows = []
    for phenotype in graph.subjects(ODIM.featureOfInterest, None):
        if not isinstance(phenotype, URIRef) or not _is_phenotype_node(phenotype):
            continue
        participant = graph.value(phenotype, ODIM.featureOfInterest)
        date = graph.value(phenotype, ODIM.resultTime)
        for cls in graph.objects(phenotype, RDF.type):
            if not isinstance(cls, URIRef):
                continue
            rows.append(
                {
                    "phenotype": _curie_name(cls),
                    "participant": str(participant).split("Participant_", 1)[-1] if participant else "",
                    "segment_date": str(date) if date else "",
                }
            )
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).drop_duplicates()


def trace_phenotypes(graph: Graph) -> pd.DataFrame:
    rows = []
    for phenotype in graph.subjects(ODIM.featureOfInterest, None):
        if not isinstance(phenotype, URIRef) or not _is_phenotype_node(phenotype):
            continue
        participant = graph.value(phenotype, ODIM.featureOfInterest)
        date = graph.value(phenotype, ODIM.resultTime)
        phenotype_types = [cls for cls in graph.objects(phenotype, RDF.type) if isinstance(cls, URIRef)]
        rules = list(graph.objects(phenotype, ODIM.triggeredByRule))
        if not rules:
            rules = [None]

        features = list(graph.objects(phenotype, ODIM.usesFeature))
        evidences = list(graph.objects(phenotype, ODIM.usesEvidence))

        def add_row(*, rule, evidence_type, evidence_uri):
            feature_class = None
            feature_value = None
            source_metric = None
            if evidence_uri is not None:
                types = [cls for cls in graph.objects(evidence_uri, RDF.type) if isinstance(cls, URIRef)]
                if types:
                    feature_class = _curie_name(types[0])
                value = graph.value(evidence_uri, ODIM.hasValue)
                if isinstance(value, Literal):
                    feature_value = str(value)
                metric_node = graph.value(evidence_uri, ODIM.wasDerivedFrom)
                if isinstance(metric_node, URIRef):
                    source_metric = _curie_name(metric_node)

            for cls in phenotype_types or [None]:
                rows.append(
                    {
                        "phenotype": _curie_name(cls) if isinstance(cls, URIRef) else "",
                        "participant": str(participant).split("Participant_", 1)[-1] if participant else "",
                        "segment_date": str(date) if date else "",
                        "rule": str(rule) if rule is not None else "",
                        "evidence_type": evidence_type,
                        "evidence_class": feature_class or "",
                        "evidence_id": str(evidence_uri) if evidence_uri is not None else "",
                        "evidence_value": feature_value or "",
                        "source_metric": source_metric or "",
                    }
                )

        if features:
            for rule in rules:
                for feat in features:
                    add_row(rule=rule, evidence_type="feature", evidence_uri=feat)
        if evidences:
            for rule in rules:
                for ev in evidences:
                    add_row(rule=rule, evidence_type="evidence", evidence_uri=ev)
        if not features and not evidences:
            for rule in rules:
                add_row(rule=rule, evidence_type="unknown", evidence_uri=None)

    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).drop_duplicates()


def summarize_trace(trace: pd.DataFrame, *, max_paths: int = 3) -> pd.DataFrame:
    if trace.empty:
        return pd.DataFrame()
    keys = ["phenotype", "participant", "segment_date"]
    grouped = trace.groupby(keys + ["rule"], dropna=False).size().reset_index(name="evidence_count")
    summary_rows = []
    for key_vals, subset in grouped.groupby(keys, dropna=False):
        subset = subset.sort_values("evidence_count", ascending=False)
        top = subset.head(max_paths)
        primary = top.iloc[0]["rule"] if not top.empty else ""
        secondary = [row["rule"] for _, row in top.iloc[1:].iterrows() if row["rule"]]
        summary_rows.append(
            {
                "phenotype": key_vals[0],
                "participant": key_vals[1],
                "segment_date": key_vals[2],
                "primary_path": primary or "",
                "secondary_paths": ";".join(secondary),
                "path_count": int(len(subset)),
                "evidence_count": int(subset["evidence_count"].sum()),
            }
        )
    return pd.DataFrame(summary_rows)


__all__ = [
    "load_feature_plan",
    "load_metric_mapping",
    "build_graph",
    "apply_rules",
    "inferred_phenotypes",
    "trace_phenotypes",
    "summarize_trace",
]
