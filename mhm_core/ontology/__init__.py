"""MHM core ontology compatibility API."""

from connect_summary.ontology.catalog import load_metric_catalog, load_unification_catalog
from connect_summary.ontology.config import load_unification_spec, select_features, write_feature_plan
from connect_summary.ontology.reason import (
    apply_rules,
    build_graph,
    inferred_phenotypes,
    load_feature_plan,
    load_metric_mapping,
    summarize_trace,
    trace_phenotypes,
)
from connect_summary.ontology.unify import merge_unified_outputs, unify_features_for_participant

__all__ = [
    "apply_rules",
    "build_graph",
    "inferred_phenotypes",
    "load_feature_plan",
    "load_metric_catalog",
    "load_metric_mapping",
    "load_unification_catalog",
    "load_unification_spec",
    "merge_unified_outputs",
    "select_features",
    "summarize_trace",
    "trace_phenotypes",
    "unify_features_for_participant",
    "write_feature_plan",
]

