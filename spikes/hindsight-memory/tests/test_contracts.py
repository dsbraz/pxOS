import asyncio
import json
from types import SimpleNamespace

import pytest

from spike.experiment import LABELS, memory_item
from spike.settings import ROOT


def test_fixture_parity_with_graphiti():
    for name in ("episodes.json", "queries.json"):
        assert (ROOT / "fixtures" / name).read_bytes() == (
            ROOT.parent / "graphiti-memory/fixtures" / name
        ).read_bytes()


def test_gold_is_not_sent_to_memory():
    episode = json.loads((ROOT / "fixtures/episodes.json").read_text())[0]
    original = memory_item(episode)
    episode["expected"] = "GABARITO QUE NUNCA DEVE IR AO MODELO"
    episode["participants"] = ["ID-INVENTADO"]
    assert memory_item(episode) == original
    assert original["document_id"] == episode["source_id"]
    assert original["tags"] == ["access:public"]


def test_native_label_schema_without_fixture_identifiers():
    from hindsight_api.engine.retain.entity_labels import parse_entity_labels

    parsed = parse_entity_labels(LABELS)
    assert len(parsed.attributes) == 4
    assert not any(s in json.dumps(LABELS) for s in ("P-101", "P-202", "CMP-1", "Ana"))


@pytest.fixture
def policy(monkeypatch):
    from spike import hooks

    monkeypatch.setattr(hooks, "keys", lambda: {"admin": "admin-test", "public": "reader-test"})
    return hooks.SpikePolicy({})


def context(key):
    return SimpleNamespace(request_context=SimpleNamespace(api_key=key))


def test_reader_scope_is_strict_and_admin_unscoped(policy):
    scope = asyncio.run(policy.resolve_tag_scope(context("reader-test")))
    assert scope[0].tags == ["access:public"]
    assert scope[0].match == "any_strict"
    assert asyncio.run(policy.resolve_tag_scope(context("admin-test"))) is None


def test_reader_cannot_retain(policy):
    assert not asyncio.run(policy.validate_retain(context("reader-test"))).allowed
    assert asyncio.run(policy.validate_retain(context("admin-test"))).allowed


def test_wrong_project_is_rejected_before_loading_credentials(monkeypatch):
    from spike.settings import configure

    monkeypatch.setenv("SPIKE_GCP_PROJECT", "bud2-saas-homolog")
    with pytest.raises(ValueError, match="só pode usar pxos-spikes"):
        configure()


def test_isolated_auth_preserves_source_and_existing_api_keys(tmp_path, monkeypatch):
    from spike import auth

    monkeypatch.setattr(auth, "ROOT", tmp_path / "spike")
    auth.ROOT.mkdir()
    source = tmp_path / "source.json"
    source.write_text(
        json.dumps(
            {
                "type": "authorized_user",
                "refresh_token": "fake-test-token",
                "quota_project_id": "another-project",
            }
        )
    )
    original = source.read_bytes()
    auth.prepare(source)
    api_path = auth.ROOT / ".secrets/api.json"
    keys_before = api_path.read_bytes()
    auth.prepare(source)
    assert source.read_bytes() == original
    assert api_path.read_bytes() == keys_before
    adc_path = auth.ROOT / ".secrets/adc.json"
    adc = json.loads(adc_path.read_text())
    assert adc["quota_project_id"] == adc["source_credentials"]["quota_project_id"] == "pxos-spikes"
    assert (
        "spike-runner@pxos-spikes.iam.gserviceaccount.com"
        in adc["service_account_impersonation_url"]
    )
    assert adc_path.stat().st_mode & 0o777 == 0o600
    assert api_path.stat().st_mode & 0o777 == 0o600
