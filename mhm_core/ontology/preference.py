"""Shared source-preference resolution for unification feature variants."""
from __future__ import annotations

from collections import OrderedDict
from typing import Iterable, List, Mapping, Sequence, TypeVar


DEFAULT_SOURCE_PREFERENCE: tuple[str, ...] = ("rapids", "derived", "metric")

T = TypeVar("T")


def normalize_source_preference(prefer: Sequence[str] | None) -> List[str]:
    ordered: "OrderedDict[str, None]" = OrderedDict()
    for raw in prefer or []:
        value = str(raw or "").strip().lower()
        if not value:
            continue
        ordered[value] = None
    for fallback in DEFAULT_SOURCE_PREFERENCE:
        ordered.setdefault(fallback, None)
    return list(ordered.keys())


def source_type_from_method(method: str, inputs: object) -> str:
    normalized_method = str(method or "").strip().lower()
    if normalized_method == "rapids_reduce":
        return "rapids"
    if normalized_method == "column":
        rows: Iterable[object]
        if isinstance(inputs, list):
            rows = inputs
        else:
            rows = [inputs]
        for raw in rows:
            if not isinstance(raw, Mapping):
                continue
            source_metric = str(raw.get("source_metric") or "").strip()
            if source_metric.startswith("derived:"):
                return "derived"
        return "metric"
    return "metric"


def select_preferred_variant(candidates: Sequence[T], *, prefer: Sequence[str] | None, method_attr: str, inputs_attr: str) -> T:
    if not candidates:
        raise ValueError("select_preferred_variant requires at least one candidate")
    ordered_prefer = normalize_source_preference(prefer)
    buckets: dict[str, List[T]] = {}
    for candidate in candidates:
        method = getattr(candidate, method_attr, "")
        inputs = getattr(candidate, inputs_attr, None)
        source_type = source_type_from_method(str(method or ""), inputs)
        buckets.setdefault(source_type, []).append(candidate)
    for source_type in ordered_prefer:
        if buckets.get(source_type):
            return buckets[source_type][0]
    return candidates[0]


def dedupe_features_by_id(features: Sequence[T], *, prefer: Sequence[str] | None, feature_id_attr: str = "feature_id") -> List[T]:
    grouped: "OrderedDict[str, List[T]]" = OrderedDict()
    for feature in features:
        feature_id = str(getattr(feature, feature_id_attr, "") or "").strip()
        if not feature_id:
            continue
        grouped.setdefault(feature_id, []).append(feature)
    selected: List[T] = []
    for variants in grouped.values():
        selected.append(
            select_preferred_variant(
                variants,
                prefer=prefer,
                method_attr="method",
                inputs_attr="inputs",
            )
        )
    return selected


__all__ = [
    "DEFAULT_SOURCE_PREFERENCE",
    "dedupe_features_by_id",
    "normalize_source_preference",
    "select_preferred_variant",
    "source_type_from_method",
]
