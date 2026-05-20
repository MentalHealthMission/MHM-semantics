"""Ontology pipeline profile registrations."""

from __future__ import annotations

from typing import TYPE_CHECKING, Dict, Type

from mhm_core.pipeline.plugins.base import PipelineProfilePlugin

if TYPE_CHECKING:  # pragma: no cover
    from mhm_core.pipeline.steps.base import PipelineStep


class OntologyPipelineProfile(PipelineProfilePlugin):
    profile_id = "ontology"

    def register_steps(self, registry: Dict[str, Type["PipelineStep"]]) -> None:
        from mhm_core.pipeline.integrations.ontology_reason import OntologyReasonStep
        from mhm_core.pipeline.integrations.ontology_select import OntologySelectStep
        from mhm_core.pipeline.integrations.ontology_unify import OntologyUnifyStep

        steps: Dict[str, Type["PipelineStep"]] = {
            "ontology_select": OntologySelectStep,
            "ontology_unify": OntologyUnifyStep,
            "ontology_reason": OntologyReasonStep,
        }
        registry.update(steps)
        for name, step_cls in steps.items():
            registry[f"ontology.{name}"] = step_cls


__all__ = ["OntologyPipelineProfile"]
