"""Parse ontology mapping definitions from OWL files."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional
import xml.etree.ElementTree as ET


ODIM_NS = "http://connectdigitalstudy.com/ontology#"
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


def load_metric_catalog(paths: Iterable[Path]) -> Dict[str, Dict[str, object]]:
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
                if tag == f"{{{ODIM_NS}}}metricId":
                    metric_id = (child.text or "").strip()
                elif tag == f"{{{ODIM_NS}}}observedProperty":
                    observed = child.attrib.get(f"{{{RDF_NS}}}resource")
                    if observed and observed.startswith(ODIM_NS):
                        observed = f"odim:{observed.split('#', 1)[1]}"
                elif tag == f"{{{ODIM_NS}}}device":
                    device = (child.text or "").strip()
                elif tag == f"{{{ODIM_NS}}}hasCategory":
                    cat = child.attrib.get(f"{{{RDF_NS}}}resource")
                    if cat and cat.startswith(ODIM_NS):
                        categories.append(f"odim:{cat.split('#', 1)[1]}")
                elif tag == f"{{{ODIM_NS}}}platform":
                    platform = child.attrib.get(f"{{{RDF_NS}}}resource") or (child.text or "").strip()
                    if platform and platform.startswith(ODIM_NS):
                        platform = platform.split("#", 1)[1]
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


def load_unification_catalog(paths: Iterable[Path]) -> List[UnificationOntologyEntry]:
    entries: List[UnificationOntologyEntry] = []
    for path in paths:
        if not path.exists():
            continue
        root = ET.fromstring(path.read_text(encoding="utf-8"))
        input_nodes: Dict[str, UnificationInput] = {}
        for node in _iter_named_individuals(root):
            types = {child.attrib.get(f"{{{RDF_NS}}}resource") for child in node if child.tag == f"{{{RDF_NS}}}type"}
            if ODIM_NS + "UnificationInput" not in types:
                continue
            input_id = node.attrib.get(f"{{{RDF_NS}}}about")
            if not input_id:
                continue
            payload = UnificationInput()
            for child in list(node):
                tag = child.tag
                text = (child.text or "").strip()
                if tag == f"{{{ODIM_NS}}}inputMetric":
                    payload.metric = text
                elif tag == f"{{{ODIM_NS}}}inputTimeColumn":
                    payload.time_column = text
                elif tag == f"{{{ODIM_NS}}}inputValueColumn":
                    payload.value_column = text
                elif tag == f"{{{ODIM_NS}}}inputStartColumn":
                    payload.start_column = text
                elif tag == f"{{{ODIM_NS}}}inputEndColumn":
                    payload.end_column = text
                elif tag == f"{{{ODIM_NS}}}inputUnlockDurationColumn":
                    payload.unlock_duration_column = text
                elif tag == f"{{{ODIM_NS}}}inputUnlockCountColumn":
                    payload.unlock_count_column = text
                elif tag == f"{{{ODIM_NS}}}inputStateColumn":
                    payload.state_column = text
                elif tag == f"{{{ODIM_NS}}}inputPriority":
                    try:
                        payload.priority = int(text)
                    except ValueError:
                        payload.priority = None
                elif tag == f"{{{ODIM_NS}}}inputSourceMetric":
                    payload.source_metric = text
                elif tag == f"{{{ODIM_NS}}}inputPath":
                    payload.path = text
                elif tag == f"{{{ODIM_NS}}}inputSegmentColumn":
                    payload.segment_column = text
                elif tag == f"{{{ODIM_NS}}}inputSensor":
                    payload.sensor = text
                elif tag == f"{{{ODIM_NS}}}inputProvider":
                    payload.provider = text
                elif tag == f"{{{ODIM_NS}}}inputFeature":
                    payload.feature = text
                elif tag == f"{{{ODIM_NS}}}inputLabel":
                    payload.label = text
                elif tag == f"{{{ODIM_NS}}}inputRapidsDir":
                    payload.rapids_dir = text
                elif tag == f"{{{ODIM_NS}}}inputCumulative":
                    lowered = text.lower()
                    if lowered in {"true", "1", "yes"}:
                        payload.cumulative = True
                    elif lowered in {"false", "0", "no"}:
                        payload.cumulative = False
            input_nodes[input_id] = payload

        for node in _iter_named_individuals(root):
            types = {child.attrib.get(f"{{{RDF_NS}}}resource") for child in node if child.tag == f"{{{RDF_NS}}}type"}
            if ODIM_NS + "UnificationDefinition" not in types:
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
                if tag == f"{{{ODIM_NS}}}unificationId":
                    unification_id = (child.text or "").strip()
                elif tag == f"{{{ODIM_NS}}}odimFeature":
                    odim_feature = child.attrib.get(f"{{{RDF_NS}}}resource")
                    if odim_feature and odim_feature.startswith(ODIM_NS):
                        odim_feature = f"odim:{odim_feature.split('#', 1)[1]}"
                elif tag == f"{{{ODIM_NS}}}unifyMethod":
                    method = (child.text or "").strip()
                elif tag == f"{{{ODIM_NS}}}outputColumn":
                    output_column = (child.text or "").strip()
                elif tag == f"{{{ODIM_NS}}}selectionSameDay":
                    value = (child.text or "").strip()
                    if value:
                        selection["same_day"] = value
                elif tag == f"{{{ODIM_NS}}}paramCombine":
                    value = (child.text or "").strip()
                    if value:
                        params["combine"] = value
                elif tag == f"{{{ODIM_NS}}}hasInput":
                    ref = child.attrib.get(f"{{{RDF_NS}}}resource")
                    if ref:
                        input_refs.append(ref)
                elif tag == f"{{{ODIM_NS}}}hasCategory":
                    cat = child.attrib.get(f"{{{RDF_NS}}}resource")
                    if cat and cat.startswith(ODIM_NS):
                        categories.append(f"odim:{cat.split('#', 1)[1]}")
                elif tag == f"{{{ODIM_NS}}}usesMetric":
                    metric = (child.text or "").strip()
                    if metric:
                        metrics.append(metric)
                elif tag == f"{{{ODIM_NS}}}rapidsSensor":
                    sensor = (child.text or "").strip()
                    if sensor:
                        sensors.append(sensor)
                elif tag == f"{{{ODIM_NS}}}rapidsProvider":
                    provider = (child.text or "").strip()
                    if provider:
                        providers.append(provider)
                elif tag == f"{{{ODIM_NS}}}rapidsFeature":
                    feature = (child.text or "").strip()
                    if feature:
                        features.append(feature)
                elif tag == f"{{{ODIM_NS}}}rapidsLabel":
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
