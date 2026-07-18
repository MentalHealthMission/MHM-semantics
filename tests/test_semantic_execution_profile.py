from __future__ import annotations

import tempfile
import textwrap
import unittest
from pathlib import Path

from rdflib import Graph, Literal, Namespace, RDF
from rdflib.namespace import XSD

from mhm_core.ontology.execution_profile import (
    ExecutionProfileError,
    parse_execution_profile,
    validate_profile_rules,
)
from mhm_core.ontology.reason import apply_rules
from mhm_core.ontology.spec_builder import build_plan


class SemanticExecutionProfileTests(unittest.TestCase):
    def test_parses_nested_requirements_and_binds_typed_parameters(self) -> None:
        profile = parse_execution_profile(
            {
                "schemaVersion": 1,
                "profileId": "fixture",
                "namespaces": {"odim": "https://example.org/odim#"},
                "operations": [
                    {
                        "id": "semantic:fixture",
                        "label": "Fixture phenotype",
                        "output": {"concept": "odim:Fixture", "kind": "phenotype"},
                        "rule": {"id": "fixture", "path": "rules/fixture.rq"},
                        "requirements": {
                            "allOf": [
                                {"concept": "odim:ScreenEvidence"},
                                {
                                    "anyOf": [
                                        {"concept": "odim:StepEvidence"},
                                        {"concept": "odim:HeartEvidence"},
                                    ]
                                },
                            ]
                        },
                        "parameters": [
                            {
                                "name": "step_threshold",
                                "type": "integer",
                                "default": 5000,
                                "minimum": 0,
                                "unit": "steps/day",
                            }
                        ],
                    }
                ],
            }
        )

        operation = profile.operations[0]
        self.assertEqual(
            operation.requirements.concepts,
            {"odim:ScreenEvidence", "odim:StepEvidence", "odim:HeartEvidence"},
        )
        self.assertEqual(operation.bind_parameters(), {"step_threshold": 5000})
        self.assertEqual(operation.bind_parameters({"step_threshold": 3000}), {"step_threshold": 3000})
        with self.assertRaisesRegex(ExecutionProfileError, "requires an integer"):
            operation.bind_parameters({"step_threshold": 3.5})

    def test_rule_validation_checks_output_dependencies_and_parameters(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rules = root / "rules"
            rules.mkdir()
            (rules / "fixture.rq").write_text(
                textwrap.dedent(
                    """
                    PREFIX odim: <https://example.org/odim#>
                    PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
                    CONSTRUCT { ?result a odim:Fixture . }
                    WHERE {
                      ?evidence a odim:StepEvidence .
                      VALUES (?step_threshold) { (5000) }
                      FILTER(xsd:double(?value) < ?step_threshold)
                    }
                    """
                ),
                encoding="utf-8",
            )
            profile = parse_execution_profile(
                {
                    "schemaVersion": 1,
                    "profileId": "fixture",
                    "namespaces": {"odim": "https://example.org/odim#"},
                    "operations": [
                        {
                            "id": "semantic:fixture",
                            "label": "Fixture",
                            "output": {"concept": "odim:Fixture", "kind": "phenotype"},
                            "rule": {"id": "fixture", "path": "rules/fixture.rq"},
                            "requirements": {"concept": "odim:StepEvidence"},
                            "parameters": [
                                {"name": "step_threshold", "type": "integer", "default": 5000}
                            ],
                        }
                    ],
                }
            )

            validate_profile_rules(profile, repo_root=root)

    def test_rejects_absolute_rule_paths_and_unknown_namespace_prefixes(self) -> None:
        base = {
            "schemaVersion": 1,
            "profileId": "fixture",
            "namespaces": {"odim": "https://example.org/odim#"},
            "operations": [
                {
                    "id": "semantic:fixture",
                    "label": "Fixture",
                    "output": {"concept": "missing:Fixture", "kind": "phenotype"},
                    "rule": {"id": "fixture", "path": "/tmp/fixture.rq"},
                    "requirements": {"allOf": []},
                }
            ],
        }
        with self.assertRaisesRegex(ExecutionProfileError, "Unknown namespace prefix"):
            parse_execution_profile(base)

    def test_rule_threshold_override_is_bound_without_rewriting_sparql(self) -> None:
        odim = Namespace("http://connectdigitalstudy.com/ontology#")
        graph = Graph()
        participant = odim.Participant_fixture
        feature = odim.Feature_steps_fixture
        graph.add((feature, RDF.type, odim.DailyStepCount))
        graph.add((feature, odim.featureOfInterest, participant))
        graph.add((feature, odim.resultTime, Literal("2026-01-01", datatype=XSD.date)))
        graph.add((feature, odim.hasValue, Literal(4000)))
        with tempfile.TemporaryDirectory() as tmp:
            rule = Path(tmp) / "steps_evidence.rq"
            rule.write_text(
                textwrap.dedent(
                    """
                    PREFIX odim: <http://connectdigitalstudy.com/ontology#>
                    PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
                    CONSTRUCT { ?result a odim:EnnuiStepsEvidence . }
                    WHERE {
                      ?feature a odim:DailyStepCount ; odim:hasValue ?steps .
                      VALUES (?ennui_steps_threshold) { (5000) }
                      FILTER(xsd:double(?steps) < ?ennui_steps_threshold)
                      BIND(odim:Evidence_fixture AS ?result)
                    }
                    """
                ),
                encoding="utf-8",
            )
            default_graph = apply_rules(graph=Graph() + graph, rule_path=rule, tokens={})
            overridden_graph = apply_rules(
                graph=Graph() + graph,
                rule_path=rule,
                tokens={"ennui_steps_threshold": 3000},
            )

        self.assertTrue(any(default_graph.subjects(RDF.type, odim.EnnuiStepsEvidence)))
        self.assertFalse(any(overridden_graph.subjects(RDF.type, odim.EnnuiStepsEvidence)))

    def test_planner_acquires_every_feasible_route_but_preserves_any_of_logic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "rules").mkdir()
            (root / "rules/low.rq").write_text(
                "CONSTRUCT { ?result a odim:Low . } WHERE { ?source a odim:DailyStepCount . }",
                encoding="utf-8",
            )
            profile = root / "profile.yaml"
            profile.write_text(
                textwrap.dedent(
                    """
                    schemaVersion: 1
                    profileId: fixture
                    namespaces: {odim: 'https://example.org/odim#'}
                    operations:
                      - id: semantic:low
                        label: Low
                        output: {concept: 'odim:Low', kind: phenotype}
                        rule: {id: low, path: rules/low.rq}
                        requirements:
                          anyOf:
                            - {concept: 'odim:DailyStepCount'}
                            - {concept: 'odim:HeartRateFeature'}
                    """
                ),
                encoding="utf-8",
            )
            unification = root / "unification.yaml"
            unification.write_text(
                textwrap.dedent(
                    """
                    features:
                      - id: steps_native
                        odim_feature: odim:DailyStepCount
                        method: daily_sum
                        output_column: steps
                        inputs: [{metric: raw_steps}]
                      - id: steps_derived
                        odim_feature: odim:DailyStepCount
                        method: column
                        output_column: steps
                        inputs: [{path: '/derived/steps.csv', source_metric: 'derived:steps'}]
                      - id: heart_native
                        odim_feature: odim:HeartRateFeature
                        method: daily_sum
                        output_column: heart_rate
                        inputs: [{metric: raw_heart_rate}]
                    """
                ),
                encoding="utf-8",
            )
            derived_catalog = root / "derived-catalog.yaml"
            derived_catalog.write_text("derived_features: []\n", encoding="utf-8")
            derived_specs = root / "derived-specs.yaml"
            derived_specs.write_text("features: []\n", encoding="utf-8")
            phenotype_catalog = root / "phenotypes.yaml"
            phenotype_catalog.write_text("phenotypes: {}\n", encoding="utf-8")

            plan = build_plan(
                targets=["odim:Low"],
                metrics=[],
                prefer=["derived", "metric"],
                derived_catalog_path=derived_catalog,
                derived_spec_paths=[derived_specs],
                unification_paths=[unification],
                phenotype_catalog_path=phenotype_catalog,
                execution_profile_path=profile,
            )

        self.assertEqual(plan.semantic_operation_ids, {"semantic:low"})
        self.assertEqual(plan.unification_feature_ids, {"steps_native", "steps_derived", "heart_native"})
        self.assertEqual(plan.derived_feature_ids, {"steps"})
        self.assertEqual(plan.metrics, {"raw_steps", "raw_heart_rate"})


if __name__ == "__main__":
    unittest.main()
