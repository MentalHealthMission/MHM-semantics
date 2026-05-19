"""Parse ontology mapping definitions from OWL files."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional
import xml.etree.ElementTree as ET

from .namespaces import default_odim_namespace, odim_curie_from_uri, odim_namespaces

ODIM_NS = default_odim_namespace()
OWL_NS = "http://www.w3.org/2002/07/owl#"
RDF_NS = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
RDFS_NS = "http://www.w3.org/2000/01/rdf-schema#"


@dataclass
class UnificationInput:
    metric: Optional[str] = None
    time_column: Optional[str] = None
    value_column: Optional[str] = None
    start_column: Optional[str] = None
    end_column: Optional[str] = None
    unlock_duration_column: Optional[str] = None
    unlock_count_column: Optional[str] = None
    state_column: Optional[str] = None
    priority: Optional[int] = None
    source_metric: Optional[str] = None
    path: Optional[str] = None
    segment_column: Optional[str] = None
    sensor: Optional[str] = None
    provider: Optional[str] = None
    feature: Optional[str] = None
    label: Optional[str] = None
    rapids_dir: Optional[str] = None
    cumulative: Optional[bool] = None


@dataclass
class UnificationOntologyEntry:
    unification_id: str
    odim_feature: Optional[str]
    method: Optional[str]
    output_column: Optional[str]
    inputs: List[UnificationInput]
    selection: Dict[str, object]
    params: Dict[str, object]
    categories: List[str]


def _iter_named_individuals(root: ET.Element) -> Iterable[ET.Element]:
    return root.findall(f".//{{{OWL_NS}}}NamedIndividual")


def load_metric_catalog(paths: Iterable[Path], *, odim_namespace: str | None = None) -> Dict[str, Dict[str, object]]:
    namespaces = odim_namespaces(odim_namespace)
    mapping: Dict[str, Dict[str, object]] = {}
    for path in paths:
        if not path.exists():
            continue
        root = ET.fromstring(path.read_text(encoding="utf-8"))
        for node in _iter_named_individuals(root):
            metric_id = None
            observed = None
            device = None
            categories: List[str] = []
            platforms: List[str] = []
            doc = None
            for child in list(node):
                tag = child.tag
                if _is_odim_tag(tag, "metricId", namespaces):
                    metric_id = (child.text or "").strip()
                elif _is_odim_tag(tag, "observedProperty", namespaces):
                    observed = child.attrib.get(f"{{{RDF_NS}}}resource")
                    observed = odim_curie_from_uri(observed or "", namespace=odim_namespace)
                elif _is_odim_tag(tag, "device", namespaces):
                    device = (child.text or "").strip()
                elif _is_odim_tag(tag, "hasCategory", namespaces):
                    cat = child.attrib.get(f"{{{RDF_NS}}}resource")
                    cat = odim_curie_from_uri(cat or "", namespace=odim_namespace)
                    if cat.startswith("odim:"):
                        categories.append(cat)
                elif _is_odim_tag(tag, "platform", namespaces):
                    platform = child.attrib.get(f"{{{RDF_NS}}}resource") or (child.text or "").strip()
                    platform = odim_curie_from_uri(platform, namespace=odim_namespace)
                    if platform.startswith("odim:"):
                        platform = platform.split(":", 1)[1]
                    if platform.startswith("Platform_"):
                        platform = platform.split("Platform_", 1)[1]
                    if platform:
                        platforms.append(platform)
                elif tag == f"{{{RDFS_NS}}}comment":
                    doc = (child.text or "").strip()
            if metric_id:
                mapping.setdefault(metric_id, {})
                if observed:
                    mapping[metric_id]["observed_property"] = observed
                if device:
                    mapping[metric_id]["device"] = device
                if categories:
                    mapping[metric_id]["categories"] = sorted(set(categories))
                if platforms:
                    mapping[metric_id]["platforms"] = sorted(set(platforms))
                if doc:
                    mapping[metric_id]["doc"] = doc
    return mapping


def load_unification_catalog(paths: Iterable[Path], *, odim_namespace: str | None = None) -> List[UnificationOntologyEntry]:
    namespaces = odim_namespaces(odim_namespace)
    entries: List[UnificationOntologyEntry] = []
    for path in paths:
        if not path.exists():
            continue
        root = ET.fromstring(path.read_text(encoding="utf-8"))
        input_nodes: Dict[str, UnificationInput] = {}
        for node in _iter_named_individuals(root):
            types = {child.attrib.get(f"{{{RDF_NS}}}resource") for child in node if child.tag == f"{{{RDF_NS}}}type"}
            if not _has_odim_type(types, "UnificationInput", namespaces):
                continue
            input_id = node.attrib.get(f"{{{RDF_NS}}}about")
            if not input_id:
                continue
            payload = UnificationInput()
            for child in list(node):
                tag = child.tag
                text = (child.text or "").strip()
                if _is_odim_tag(tag, "inputMetric", namespaces):
                    payload.metric = text
                elif _is_odim_tag(tag, "inputTimeColumn", namespaces):
                    payload.time_column = text
                elif _is_odim_tag(tag, "inputValueColumn", namespaces):
                    payload.value_column = text
                elif _is_odim_tag(tag, "inputStartColumn", namespaces):
                    payload.start_column = text
                elif _is_odim_tag(tag, "inputEndColumn", namespaces):
                    payload.end_column = text
                elif _is_odim_tag(tag, "inputUnlockDurationColumn", namespaces):
                    payload.unlock_duration_column = text
                elif _is_odim_tag(tag, "inputUnlockCountColumn", namespaces):
                    payload.unlock_count_column = text
                elif _is_odim_tag(tag, "inputStateColumn", namespaces):
                    payload.state_column = text
                elif _is_odim_tag(tag, "inputPriority", namespaces):
                    try:
                        payload.priority = int(text)
                    except ValueError:
                        payload.priority = None
                elif _is_odim_tag(tag, "inputSourceMetric", namespaces):
                    payload.source_metric = text
                elif _is_odim_tag(tag, "inputPath", namespaces):
                    payload.path = text
                elif _is_odim_tag(tag, "inputSegmentColumn", namespaces):
                    payload.segment_column = text
                elif _is_odim_tag(tag, "inputSensor", namespaces):
                    payload.sensor = text
                elif _is_odim_tag(tag, "inputProvider", namespaces):
                    payload.provider = text
                elif _is_odim_tag(tag, "inputFeature", namespaces):
                    payload.feature = text
                elif _is_odim_tag(tag, "inputLabel", namespaces):
                    payload.label = text
                elif _is_odim_tag(tag, "inputRapidsDir", namespaces):
                    payload.rapids_dir = text
                elif _is_odim_tag(tag, "inputCumulative", namespaces):
                    lowered = text.lower()
                    if lowered in {"true", "1", "yes"}:
                        payload.cumulative = True
                    elif lowered in {"false", "0", "no"}:
                        payload.cumulative = False
            input_nodes[input_id] = payload

        for node in _iter_named_individuals(root):
            types = {child.attrib.get(f"{{{RDF_NS}}}resource") for child in node if child.tag == f"{{{RDF_NS}}}type"}
            if not _has_odim_type(types, "UnificationDefinition", namespaces):
                continue
            unification_id = None
            odim_feature = None
            method = None
            output_column = None
            selection: Dict[str, object] = {}
            params: Dict[str, object] = {}
            inputs: List[UnificationInput] = []
            input_refs: List[str] = []
            categories: List[str] = []
            metrics: List[str] = []
            sensors: List[str] = []
            providers: List[str] = []
            features: List[str] = []
            labels: List[str] = []
            for child in list(node):
                tag = child.tag
                if _is_odim_tag(tag, "unificationId", namespaces):
                    unification_id = (child.text or "").strip()
                elif _is_odim_tag(tag, "odimFeature", namespaces):
                    odim_feature = child.attrib.get(f"{{{RDF_NS}}}resource")
                    odim_feature = odim_curie_from_uri(odim_feature or "", namespace=odim_namespace)
                elif _is_odim_tag(tag, "unifyMethod", namespaces):
                    method = (child.text or "").strip()
                elif _is_odim_tag(tag, "outputColumn", namespaces):
                    output_column = (child.text or "").strip()
                elif _is_odim_tag(tag, "selectionSameDay", namespaces):
                    value = (child.text or "").strip()
                    if value:
                        selection["same_day"] = value
                elif _is_odim_tag(tag, "paramCombine", namespaces):
                    value = (child.text or "").strip()
                    if value:
                        params["combine"] = value
                elif _is_odim_tag(tag, "hasInput", namespaces):
                    ref = child.attrib.get(f"{{{RDF_NS}}}resource")
                    if ref:
                        input_refs.append(ref)
                elif _is_odim_tag(tag, "hasCategory", namespaces):
                    cat = child.attrib.get(f"{{{RDF_NS}}}resource")
                    cat = odim_curie_from_uri(cat or "", namespace=odim_namespace)
                    if cat.startswith("odim:"):
                        categories.append(cat)
                elif _is_odim_tag(tag, "usesMetric", namespaces):
                    metric = (child.text or "").strip()
                    if metric:
                        metrics.append(metric)
                elif _is_odim_tag(tag, "rapidsSensor", namespaces):
                    sensor = (child.text or "").strip()
                    if sensor:
                        sensors.append(sensor)
                elif _is_odim_tag(tag, "rapidsProvider", namespaces):
                    provider = (child.text or "").strip()
                    if provider:
                        providers.append(provider)
                elif _is_odim_tag(tag, "rapidsFeature", namespaces):
                    feature = (child.text or "").strip()
                    if feature:
                        features.append(feature)
                elif _is_odim_tag(tag, "rapidsLabel", namespaces):
                    label = (child.text or "").strip()
                    if label:
                        labels.append(label)
            if not unification_id:
                continue
            for ref in input_refs:
                payload = input_nodes.get(ref)
                if payload:
                    inputs.append(payload)
            if not inputs and metrics:
                for metric in metrics:
                    inputs.append(UnificationInput(metric=metric))
            if not inputs and sensors:
                for idx, sensor in enumerate(sensors):
                    inputs.append(
                        UnificationInput(
                            sensor=sensor,
                            provider=providers[idx] if idx < len(providers) else None,
                            feature=features[idx] if idx < len(features) else None,
                            label=labels[idx] if idx < len(labels) else None,
                        )
                    )
            entry = UnificationOntologyEntry(
                unification_id=unification_id,
                odim_feature=odim_feature,
                method=method,
                output_column=output_column,
                inputs=inputs,
                selection=selection,
                params=params,
                categories=sorted(set(categories)),
            )
            entries.append(entry)
    return entries


def _is_odim_tag(tag: str, local_name: str, namespaces: tuple[str, ...]) -> bool:
    return any(tag == f"{{{namespace}}}{local_name}" for namespace in namespaces)


def _has_odim_type(types: set[str | None], local_name: str, namespaces: tuple[str, ...]) -> bool:
    return any(namespace + local_name in types for namespace in namespaces)
