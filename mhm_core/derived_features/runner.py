"""Compatibility wrapper for pipeline-bound derived-feature execution.

The generic derived-feature package exposes catalogs, annotations, and registry
helpers. Executing those feature specs against a pipeline `RunContext` belongs
to the pipeline integration layer.
"""

from mhm_core.pipeline.derived_features_runner import (
    run_derived_features_for_entity,
    run_derived_features_for_participant,
)

__all__ = ["run_derived_features_for_entity", "run_derived_features_for_participant"]
