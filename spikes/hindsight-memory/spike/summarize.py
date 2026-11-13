"""Agrega evidências mecânicas; respostas semânticas exigem revisão no ADR."""

import hashlib
import json
import math
import platform
from collections import Counter
from importlib.metadata import version

from spike.settings import ROOT


def read(path):
    return json.loads(path.read_text())


def markers(value):
    text = json.dumps(value, ensure_ascii=False).lower()
    return [
        s
        for s in ("sigilo-orquidea-731", "cancelamento de financiamento", "funding cancellation")
        if s in text
    ]


def summarize(directory):
    final = read(directory / "after-ingestion.json")
    before = read(directory / "before-replay.json")
    after = read(directory / "after-replay.json")
    deleted = read(directory / "after-delete.json")

    def ids(state, kind):
        return {x["id"] for x in state[kind]}

    timings = read(directory / "timings.json")
    ingest = [
        t["seconds"]
        for t in timings
        if t["method"] == "POST" and t["route"] == "/memories" and t["principal"] == "admin"
    ][:12]
    durations = sorted(ingest)
    sources = {e["source_id"] for e in read(ROOT / "fixtures/episodes.json")}
    source_facts = [m for m in final["memories"] if m["fact_type"] != "observation"]
    observations = [m for m in final["memories"] if m["fact_type"] == "observation"]
    public_files = [
        "answer-restricted.json",
        "restricted-forged-tags.json",
        "public-snapshot.json",
        "public-routes.json",
    ]
    return {
        "bank": directory.name,
        "variant": read(directory / "manifest.json")["variant"],
        "complete": read(directory / "complete.json")["complete"],
        "memory_types": dict(Counter(m["fact_type"] for m in final["memories"])),
        "entities": len(final["entities"]),
        "source_facts_with_known_document": sum(m["document_id"] in sources for m in source_facts),
        "source_facts_with_chunk": sum(bool(m["chunk_id"]) for m in source_facts),
        "source_facts_total": len(source_facts),
        "observations_with_source_ids": sum(bool(m["source_memory_ids"]) for m in observations),
        "replay_same_memory_ids": ids(before, "memories") == ids(after, "memories"),
        "replay_same_entity_ids": ids(before, "entities") == ids(after, "entities"),
        "public_marker_hits": {name: markers(read(directory / name)) for name in public_files},
        "admin_positive_control_markers": markers(read(directory / "restricted-admin.json")),
        "public_route_statuses": {
            route: value["status"]
            for route, value in read(directory / "public-routes.json").items()
        },
        "public_retain_status": read(directory / "public-retain-denied.json")["status"],
        "after_delete_markers": markers(deleted),
        "after_delete_recall_reflect_markers": markers(
            read(directory / "restricted-after-delete.json")
        ),
        "remaining_facts_from_deleted_document": sum(
            m["document_id"] == "synthetic:e08" for m in deleted["memories"]
        ),
        "storage_audit": read(directory / "storage-audit.json"),
        "ingestion_seconds": {
            "count": len(durations),
            "p50": (durations[5] + durations[6]) / 2,
            "p95_nearest_rank": durations[math.ceil(len(durations) * 0.95) - 1],
        },
        "retrieval_latency_seconds": {
            route: {
                "count": len(values),
                "p50": (values[(len(values) - 1) // 2] + values[len(values) // 2]) / 2,
                "max": max(values),
            }
            for route in ("/memories/recall", "/reflect")
            if (values := sorted(t["seconds"] for t in timings if t["route"] == route))
        },
        "http_status_counts": dict(Counter(t["status"] for t in timings)),
        "answers": {
            p.stem: read(p)["reflect"]["body"]["text"]
            for p in sorted(directory.glob("answer-*.json"))
        },
        "semantic_precision": None,
        "semantic_recall": None,
    }


def usage():
    from prometheus_client.parser import text_string_to_metric_families

    names = {
        "hindsight_llm_calls_total": "calls",
        "hindsight_llm_tokens_input_tokens_total": "input_tokens",
        "hindsight_llm_tokens_output_tokens_total": "output_tokens",
        "hindsight_llm_tokens_thoughts_tokens_total": "thoughts_tokens",
        "hindsight_llm_tokens_cached_input_tokens_total": "cached_input_tokens",
    }
    totals = Counter()
    by_scope = {}
    files = sorted((ROOT / "runs").glob("metrics-phase*.txt"))
    for path in files:
        for family in text_string_to_metric_families(path.read_text()):
            for sample in family.samples:
                if sample.name not in names or sample.labels.get("scope") == "verification":
                    continue
                key = names[sample.name]
                totals[key] += sample.value
                scope = sample.labels.get("scope", "unknown")
                by_scope.setdefault(scope, Counter())[key] += sample.value
    return {
        "files": [p.name for p in files],
        "totals": dict(totals),
        "by_scope": {k: dict(v) for k, v in by_scope.items()},
        "notes": "Native counters; excludes startup verification, embeddings and cloud billing. Includes both full runs, review and purge probes. Not a count of every HTTP retry.",
    }


def main():
    runs = [summarize(p.parent) for p in sorted((ROOT / "runs").glob("pxos-hs-*/complete.json"))]
    data = {
        "date": "2026-11-13",
        "python": platform.python_version(),
        "versions": {
            p: version(p)
            for p in ("hindsight-api-slim", "hindsight-client", "google-genai", "asyncpg")
        },
        "hashes": {
            str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in [
                ROOT / "uv.lock",
                *sorted((ROOT / "fixtures").glob("*.json")),
                *sorted((ROOT / "spike").glob("*.py")),
            ]
        },
        "runs": runs,
        "usage": usage(),
        "purge_probes": [
            {
                "bank": p.parent.name,
                "configuration": read(p),
                "before": read(p.parent / "storage-before.json"),
                "after": read(p.parent / "storage-after.json"),
                "public_traces_status": read(p.parent / "public-traces.json")["status"],
            }
            for p in sorted((ROOT / "runs").glob("pxos-hs-purge-*/probe-complete.json"))
        ],
    }
    target = ROOT / "reports"
    target.mkdir(exist_ok=True)
    (target / "summary.json").write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    print(f"Agregadas {len(runs)} execuções completas em reports/summary.json")


if __name__ == "__main__":
    main()
