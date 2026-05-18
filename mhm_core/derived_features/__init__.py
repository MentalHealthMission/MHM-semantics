"""Generic derived-feature tooling for the MHM core."""

from .catalog import build_catalog, build_unification
from .odim_annotations import odim_computation, odim_defaults, odim_outputs
from .registry import (
    build_derived_spec_from_data_book,
    build_derived_spec_from_registry,
    build_derived_spec_from_root,
    load_decorator_metadata,
    scan_derived_feature_scripts,
)

__all__ = [
    "build_catalog",
    "build_derived_spec_from_data_book",
    "build_derived_spec_from_registry",
    "build_derived_spec_from_root",
    "build_unification",
    "load_decorator_metadata",
    "odim_computation",
    "odim_defaults",
    "odim_outputs",
    "run_derived_features_for_participant",
    "scan_derived_feature_scripts",
]


def __getattr__(name: str):
    if name == "run_derived_features_for_participant":
        from .runner import run_derived_features_for_participant

        return run_derived_features_for_participant
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
