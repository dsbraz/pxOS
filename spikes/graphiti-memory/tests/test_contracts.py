import asyncio
import json
from types import SimpleNamespace

import pytest
from graphiti_core.errors import EntityTypeValidationError
from graphiti_core.utils.ontology_utils.entity_types_utils import validate_entity_types
from linkml.generators.pydanticgen import PydanticGenerator
from pydantic import BaseModel

from spike.clients import GcloudCredentials, MeasuredModels
from spike.config import ROOT, Settings
from spike.evaluate import structural_checks
from spike.generate import generate
from spike.ontology import EDGE_TYPE_MAP, EDGE_TYPES, ENTITY_TYPES, ontology_arguments
from spike.temporal import temporal_filter


def test_generated_models_are_reproducible_across_directories(tmp_path):
    schema = tmp_path / "memory.yaml"
    schema.write_bytes((ROOT / "ontology/memory.yaml").read_bytes())
    generated = PydanticGenerator(str(schema), metadata_mode=None).serialize()
    assert generated == generate() == (ROOT / "spike/generated.py").read_text()


def test_native_graphiti_accepts_generated_entities_and_relation_fields():
    assert validate_entity_types(ENTITY_TYPES)
    from graphiti_core.edges import EntityEdge

    for model in EDGE_TYPES.values():
        assert not set(model.model_fields) & set(EntityEdge.model_fields)
        assert model.model_json_schema()["type"] == "object"
    for (source, target), relations in EDGE_TYPE_MAP.items():
        assert source in ENTITY_TYPES and target in ENTITY_TYPES
        assert all(relation in EDGE_TYPES for relation in relations)
    assert ontology_arguments("generic") == {}


def test_graphiti_rejects_reserved_fields():
    class Invalid(BaseModel):
        uuid: str

    with pytest.raises(EntityTypeValidationError):
        validate_entity_types({"Invalid": Invalid})


def test_project_never_inherits_product_configuration(monkeypatch):
    monkeypatch.delenv("SPIKE_GCP_PROJECT", raising=False)
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "bud2-saas-homolog")
    monkeypatch.setenv("SPIKE_GCP_ACCOUNT", "test@example.org")
    with pytest.raises(ValueError, match="exclusivo"):
        Settings.load()
    monkeypatch.setenv("SPIKE_GCP_PROJECT", "bud2-saas-homolog")
    with pytest.raises(ValueError, match="exclusivo"):
        Settings.load()
    monkeypatch.setenv("SPIKE_GCP_PROJECT", "pxos-spikes")
    assert Settings.load().service_account == "spike-runner@pxos-spikes.iam.gserviceaccount.com"


def test_credentials_request_explicit_project_account_and_impersonation(monkeypatch):
    settings = Settings(
        "pxos-spikes", "test@example.org", "model", "global", "embed", "us-central1", 768
    )
    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        return SimpleNamespace(returncode=0, stdout="synthetic-token")

    monkeypatch.setattr("spike.clients.subprocess.run", fake_run)
    credentials = GcloudCredentials(settings)
    credentials.refresh(None)
    assert "--project=pxos-spikes" in calls[0]
    assert "--account=test@example.org" in calls[0]
    assert (
        "--impersonate-service-account=spike-runner@pxos-spikes.iam.gserviceaccount.com" in calls[0]
    )
    assert credentials.valid


def test_metrics_record_failure_without_prompt_or_credentials(tmp_path):
    class FailingModels:
        async def generate_content(self, **kwargs):
            raise RuntimeError("sensitive error content")

    path = tmp_path / "calls.jsonl"
    measured = MeasuredModels(FailingModels(), path, "global")
    with pytest.raises(RuntimeError):
        asyncio.run(measured.generate_content(model="test", contents="sensitive prompt"))
    row = json.loads(path.read_text())
    assert row["status"] == "error" and row["seconds"] >= 0
    assert "sensitive" not in path.read_text()


def test_empty_graph_is_not_successful_evidence():
    checks = structural_checks({"nodes": [], "edges": []})
    assert checks["has_facts"] is False


def test_dangling_source_and_deleted_reference_are_detected():
    state = {
        "nodes": [],
        "edges": [
            {"type": "RELATES_TO", "properties": {"episodes": ["missing"], "fact": "example"}}
        ],
    }
    checks = structural_checks(state, "missing")
    assert checks["dangling_episode_refs"] == ["missing"]
    assert checks["deleted_episode_refs_absent"] is False


def test_temporal_filter_rejects_naive_timestamp():
    with pytest.raises(ValueError, match="timezone"):
        temporal_filter("2026-01-01T00:00:00")


def test_unreviewed_cases_never_become_zero_accuracy():
    from spike.evaluate import review_metrics

    metrics = review_metrics([{"correct": None}])
    assert metrics["reviewed_cases"] == 0
    assert metrics["accuracy_reviewed_only"] is None
    assert metrics["precision_labeled_only"] is None


def test_review_metrics_use_explicit_denominators():
    from spike.evaluate import review_metrics

    metrics = review_metrics(
        [
            {
                "correct": True,
                "correct_facts": 3,
                "incorrect_facts": 1,
                "expected_facts": 5,
                "recovered_expected_facts": 2,
            },
            {"correct": False},
            {"correct": None},
        ]
    )
    assert metrics["accuracy_reviewed_only"] == 0.5
    assert metrics["reviewed_cases"] == 2 and metrics["total_cases"] == 3
    assert metrics["precision_labeled_only"] == 0.75
    assert metrics["coverage_labeled_only"] == 0.4
