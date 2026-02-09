"""Load RAPIDS sensor-to-metric mappings from ontology files."""
from __future__ import annotations

from pathlib import Path
from typing import Dict, Iterable, Tuple

try:
    from rdflib import Graph, Literal
    from rdflib.namespace import Namespace
except ModuleNotFoundError:  # pragma: no cover - optional unless RAPIDS mapping used
    Graph = None  # type: ignore[assignment]
    Literal = None  # type: ignore[assignment]
    Namespace = None  # type: ignore[assignment]


import xml.etree.ElementTree as ET


ODIM_NS = "http://connectdigitalstudy.com/ontology#"


def _as_text(value: object) -> str:
    if value is None:
        return ""
    if Literal is not None and isinstance(value, Literal):
        return str(value)
    return str(value)


def _load_xml_mappings(paths: Iterable[Path]) -> Tuple[Dict[str, Dict[str, str]], Dict[str, str]]:
    inputs: Dict[str, Dict[str, str]] = {}
    fitbit_inputs: Dict[str, str] = {}
    for path in paths:
        if not path or not path.exists():
            continue
        tree = ET.parse(path)
        root = tree.getroot()
        for elem in root.iter():
            sensor = None
            platform = None
            metric = None
            for child in list(elem):
                tag = child.tag
                if tag.endswith("rapidsSensor"):
                    sensor = (child.text or "").strip()
                elif tag.endswith("rapidsPlatform"):
                    platform = (child.text or "").strip().upper()
                elif tag.endswith("rapidsMetric"):
                    metric = (child.text or "").strip()
            if not sensor or not metric:
                continue
            if sensor.startswith("FITBIT_"):
                fitbit_inputs[sensor] = metric
            elif platform:
                inputs.setdefault(sensor, {})[platform] = metric
            else:
                inputs.setdefault(sensor, {})["ANY"] = metric
    return inputs, fitbit_inputs


def load_rapids_input_mappings(
    paths: Iterable[Path],
) -> Tuple[Dict[str, Dict[str, str]], Dict[str, str]]:
    """Return (inputs_map, fitbit_inputs) from ontology files."""
    if Graph is None or Namespace is None:
        return _load_xml_mappings(paths)

    graph = Graph()
    for path in paths:
        if path and path.exists():
            graph.parse(path)

    odim = Namespace(ODIM_NS)
    sensor_prop = odim.rapidsSensor
    platform_prop = odim.rapidsPlatform
    metric_prop = odim.rapidsMetric

    inputs: Dict[str, Dict[str, str]] = {}
    fitbit_inputs: Dict[str, str] = {}

    for subj in graph.subjects(predicate=sensor_prop):
        sensor = _as_text(graph.value(subj, sensor_prop)).strip()
        metric = _as_text(graph.value(subj, metric_prop)).strip()
        platform = _as_text(graph.value(subj, platform_prop)).strip().upper()
        if not sensor or not metric:
            continue
        if sensor.startswith("FITBIT_"):
            fitbit_inputs[sensor] = metric
            continue
        if platform:
            inputs.setdefault(sensor, {})[platform] = metric
        else:
            inputs.setdefault(sensor, {})["ANY"] = metric

    return inputs, fitbit_inputs


__all__ = ["load_rapids_input_mappings"]
