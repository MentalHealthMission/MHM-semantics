from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

from mhm_core.ontology.catalog import load_metric_catalog
from mhm_core.ontology.spec_builder import build_plan, build_run_spec, build_semantic_pipeline_steps


class SemanticLayerBoundaryTests(unittest.TestCase):
    def test_semantic_package_import_contract(self) -> None:
        result = subprocess.run(
            [sys.executable, "scripts/check_semantic_package_contract.py"],
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["violations"], [])

    def test_semantic_kernel_imports_without_project_or_pipeline_packages(self) -> None:
        code = textwrap.dedent(
            """
            import json
            import sys

            from mhm_core.ontology.catalog import load_metric_catalog
            from mhm_core.ontology.config import load_unification_spec
            from mhm_core.ontology.spec_builder import build_plan, build_run_spec

            loaded = sorted(
                name
                for name in sys.modules
                if name.startswith("connect_summary") or name.startswith("mhm_core.pipeline")
            )
            print(json.dumps({
                "loaded": loaded,
                "symbols": [
                    load_metric_catalog.__name__,
                    load_unification_spec.__name__,
                    build_plan.__name__,
                    build_run_spec.__name__,
                ],
            }, sort_keys=True))
            """
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["loaded"], [])
        self.assertEqual(
            payload["symbols"],
            ["load_metric_catalog", "load_unification_spec", "build_plan", "build_run_spec"],
        )

    def test_generic_semantic_builder_uses_neutral_source_vocabulary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            derived_catalog = root / "derived-catalog.yaml"
            phenotype_catalog = root / "phenotype-catalog.yaml"
            unification_spec = root / "unification.yaml"
            derived_catalog.write_text("derived_features: []\n", encoding="utf-8")
            phenotype_catalog.write_text("phenotypes: {}\n", encoding="utf-8")
            unification_spec.write_text(
                textwrap.dedent(
                    """
                    features:
                      - id: daily_mood_score
                        odim_feature: odim:DailyMoodScore
                        category: odim:Wellbeing
                        method: daily_sum
                        output_column: daily_mood_score
                        inputs:
                          - metric: sensor_mood_score
                            time_column: observed_at
                            value_column: score
                    """
                ),
                encoding="utf-8",
            )

            plan = build_plan(
                targets=["odim:DailyMoodScore"],
                metrics=[],
                prefer=["metric"],
                derived_catalog_path=derived_catalog,
                derived_spec_paths=[],
                unification_paths=[unification_spec],
                phenotype_catalog_path=phenotype_catalog,
            )
            spec = build_run_spec(
                plan=plan,
                run_id="semantic-demo",
                created_by="test",
                created_at="2026-05-18T00:00:00Z",
                source_bucket="",
                source_prefix="semantic-demo",
                discover_all=False,
                entities=["entity-alpha"],
                groups=["cohort-a"],
                entity_group_map={"entity-alpha": "cohort-a"},
                workspace_root="/tmp/mhm-semantic-demo",
                run_subdir="runs/{run_id}",
                outputs={},
                redact_rules=[],
                derived_spec_path=None,
                rapids_template_path=None,
                unification_paths=[unification_spec],
                ontology_mapping_path=root / "semantic-map.owl",
                ontology_files=[],
                include_ontology_steps=True,
            )
            semantic_steps = build_semantic_pipeline_steps(
                plan=plan,
                workspace_root="/tmp/mhm-semantic-demo",
                run_subdir="runs/{run_id}",
                derived_spec_path=None,
                rapids_template_path=None,
                unification_paths=[unification_spec],
                ontology_mapping_path=root / "semantic-map.owl",
                ontology_files=[],
                include_ontology_steps=True,
            )

        self.assertEqual(plan.metrics, {"sensor_mood_score"})
        self.assertTrue(plan.needs_unify)
        self.assertEqual([step["type"] for step in semantic_steps], ["ontology_select", "ontology_unify"])
        self.assertNotIn("download", [step["type"] for step in semantic_steps])
        self.assertEqual(
            [step["type"] for step in spec["processing"]["steps"]],
            ["ontology_select", "ontology_unify"],
        )
        self.assertEqual(
            spec["source"],
            {
                "bucket": "",
                "prefix": "semantic-demo",
                "discover_all": False,
                "entities": ["entity-alpha"],
                "groups": ["cohort-a"],
                "entity_group_map": {"entity-alpha": "cohort-a"},
            },
        )
        self.assertNotIn("participants", spec["source"])
        self.assertNotIn("sites", spec["source"])
        self.assertEqual(spec["filters"]["include_metrics"], ["sensor_mood_score"])
        rendered = json.dumps(spec, sort_keys=True)
        self.assertNotIn("ontology/connect", rendered)
        self.assertNotIn("connect-ontology", rendered)

    def test_ontology_catalog_uses_neutral_category_curie_with_historical_alias_compatibility(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            owl_path = root / "semantic-map.owl"
            derived_catalog = root / "derived-catalog.yaml"
            phenotype_catalog = root / "phenotype-catalog.yaml"
            derived_catalog.write_text("derived_features: []\n", encoding="utf-8")
            phenotype_catalog.write_text("phenotypes: {}\n", encoding="utf-8")
            owl_path.write_text(
                textwrap.dedent(
                    """\
                    <rdf:RDF
                      xmlns:owl="http://www.w3.org/2002/07/owl#"
                      xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
                      xmlns:rdfs="http://www.w3.org/2000/01/rdf-schema#"
                      xmlns:odim="http://connectdigitalstudy.com/ontology#">
                      <owl:NamedIndividual rdf:about="http://connectdigitalstudy.com/ontology#Metric_sensor_mood_score">
                        <rdf:type rdf:resource="http://connectdigitalstudy.com/ontology#MetricDefinition" />
                        <odim:metricId>sensor_mood_score</odim:metricId>
                        <odim:observedProperty rdf:resource="http://connectdigitalstudy.com/ontology#MoodState" />
                        <odim:hasCategory rdf:resource="http://connectdigitalstudy.com/ontology#Category_MOOD" />
                        <rdfs:comment>Example semantic fixture metric.</rdfs:comment>
                      </owl:NamedIndividual>
                    </rdf:RDF>
                    """
                ),
                encoding="utf-8",
            )

            catalog = load_metric_catalog([owl_path])
            plan = build_plan(
                targets=["connect:Category_MOOD"],
                metrics=[],
                prefer=["metric"],
                derived_catalog_path=derived_catalog,
                derived_spec_paths=[],
                unification_paths=[],
                phenotype_catalog_path=phenotype_catalog,
                ontology_paths=[owl_path],
            )

        self.assertEqual(catalog["sensor_mood_score"]["categories"], ["odim:Category_MOOD"])
        self.assertEqual(plan.metrics, {"sensor_mood_score"})

    def test_odim_namespace_is_configurable_with_legacy_alias_compatibility(self) -> None:
        from mhm_core.ontology.namespaces import HISTORICAL_ODIM_NAMESPACE, normalize_namespace

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            owl_path = root / "semantic-map.owl"
            legacy_path = root / "legacy-map.owl"
            custom_ns = "https://example.org/odim#"
            owl_path.write_text(
                textwrap.dedent(
                    f"""\
                    <rdf:RDF
                      xmlns:owl="http://www.w3.org/2002/07/owl#"
                      xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
                      xmlns:odim="{custom_ns}">
                      <owl:NamedIndividual rdf:about="{custom_ns}Metric_sensor_mood_score">
                        <rdf:type rdf:resource="{custom_ns}MetricDefinition" />
                        <odim:metricId>sensor_mood_score</odim:metricId>
                        <odim:observedProperty rdf:resource="{custom_ns}MoodState" />
                      </owl:NamedIndividual>
                    </rdf:RDF>
                    """
                ),
                encoding="utf-8",
            )
            legacy_path.write_text(
                textwrap.dedent(
                    f"""\
                    <rdf:RDF
                      xmlns:owl="http://www.w3.org/2002/07/owl#"
                      xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
                      xmlns:odim="{HISTORICAL_ODIM_NAMESPACE}">
                      <owl:NamedIndividual rdf:about="{HISTORICAL_ODIM_NAMESPACE}Metric_legacy_mood_score">
                        <rdf:type rdf:resource="{HISTORICAL_ODIM_NAMESPACE}MetricDefinition" />
                        <odim:metricId>legacy_mood_score</odim:metricId>
                        <odim:observedProperty rdf:resource="{HISTORICAL_ODIM_NAMESPACE}MoodState" />
                      </owl:NamedIndividual>
                    </rdf:RDF>
                    """
                ),
                encoding="utf-8",
            )

            custom_catalog = load_metric_catalog([owl_path], odim_namespace=custom_ns)
            legacy_catalog = load_metric_catalog([legacy_path], odim_namespace=custom_ns)

        self.assertEqual(normalize_namespace("https://example.org/odim"), custom_ns)
        self.assertEqual(custom_catalog["sensor_mood_score"]["observed_property"], "odim:MoodState")
        self.assertEqual(legacy_catalog["legacy_mood_score"]["observed_property"], "odim:MoodState")

    def test_reasoning_graph_runs_on_minimal_fixture(self) -> None:
        try:
            import pandas as pd
            from mhm_core.ontology.reason import FeaturePlanEntry, build_graph
        except ModuleNotFoundError as exc:
            self.skipTest(f"semantic reasoning optional dependency unavailable: {exc.name}")

        unified = pd.DataFrame(
            [
                {
                    "segment_date": "2026-05-18",
                    "daily_mood_score": 7,
                }
            ]
        )
        graph = build_graph(
            participant_id="entity-alpha",
            unified=unified,
            feature_plan=[
                FeaturePlanEntry(
                    feature_id="daily_mood_score",
                    odim_feature="odim:DailyMoodScore",
                    output_column="daily_mood_score",
                    computation={},
                )
            ],
            metric_mapping={},
            ontology_paths=[],
        )

        self.assertGreater(len(graph), 0)
        self.assertIn("DailyMoodScore", graph.serialize(format="turtle"))
        self.assertIn("entity-alpha", graph.serialize(format="turtle"))


if __name__ == "__main__":
    unittest.main()
