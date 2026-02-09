"""Ontology integration utilities."""

from .config import load_metric_mapping, load_unification_spec, select_features, write_feature_plan

__all__ = [
    "load_metric_mapping",
    "load_unification_spec",
    "select_features",
    "write_feature_plan",
]

try:  # Avoid hard dependency when only config utilities are needed.
    from .unify import unify_features_for_participant, merge_unified_outputs
    from .reason import build_graph, apply_rules, inferred_phenotypes

    __all__ += [
        "unify_features_for_participant",
        "merge_unified_outputs",
        "build_graph",
        "apply_rules",
        "inferred_phenotypes",
    ]
except Exception:
    pass
