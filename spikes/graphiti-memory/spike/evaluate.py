"""Checagens estruturais + ficha de revisão semântica; sem LLM julgando a si próprio."""

import json
import math
from pathlib import Path
from statistics import median

SECRET = "SIGILO-ORQUIDEA-731"


def structural_checks(state, deleted_uuid=None):
    facts = [r["properties"] for r in state["edges"] if r["type"] == "RELATES_TO"]
    episodes = {n["properties"]["uuid"] for n in state["nodes"] if "Episodic" in n["labels"]}
    entities = [n["properties"] for n in state["nodes"] if "Entity" in n["labels"]]
    # Ausência de fatos nunca conta como sucesso de cobertura/evidência.
    checks = {
        "has_facts": bool(facts),
        "facts_count": len(facts),
        "facts_with_episode_refs": sum(bool(f.get("episodes")) for f in facts),
        "dangling_episode_refs": sorted(
            {e for f in facts for e in f.get("episodes", []) if e not in episodes}
        ),
        "secret_in_entity_or_fact": SECRET in json.dumps(entities + facts),
    }
    if deleted_uuid:
        checks["deleted_episode_absent"] = deleted_uuid not in episodes
        checks["deleted_episode_refs_absent"] = all(
            deleted_uuid not in f.get("episodes", []) for f in facts
        )
    return checks


def review_metrics(rows):
    reviewed = [r for r in rows if isinstance(r.get("correct"), bool)]
    counts = ("correct_facts", "incorrect_facts", "expected_facts", "recovered_expected_facts")
    labeled = [r for r in rows if all(type(r.get(k)) is int for k in counts)]
    for row in labeled:
        if (
            any(row[k] < 0 for k in counts)
            or row["recovered_expected_facts"] > row["expected_facts"]
        ):
            raise ValueError("Contagens de revisão inválidas")
    correct = sum(r["correct_facts"] for r in labeled)
    incorrect = sum(r["incorrect_facts"] for r in labeled)
    expected = sum(r["expected_facts"] for r in labeled)
    recovered = sum(r["recovered_expected_facts"] for r in labeled)
    return {
        "reviewed_cases": len(reviewed),
        "total_cases": len(rows),
        "accuracy_reviewed_only": sum(r["correct"] for r in reviewed) / len(reviewed)
        if reviewed
        else None,
        "fact_labeled_cases": len(labeled),
        "precision_labeled_only": correct / (correct + incorrect) if correct + incorrect else None,
        "coverage_labeled_only": recovered / expected if expected else None,
    }


def report(run_dir):
    run_dir = Path(run_dir)
    manifest = json.loads((run_dir / "manifest.json").read_text())
    observations = json.loads((run_dir / "observations.json").read_text())
    calls = [json.loads(line) for line in (run_dir / "calls.jsonl").read_text().splitlines()]
    usage = [c["usage"] for c in calls if c.get("usage")]
    tokens = sum(u.get("total_token_count", 0) or 0 for u in usage)
    review = json.loads((run_dir / "review.json").read_text())
    metrics = review_metrics(review)
    durations = sorted(
        json.loads(p.read_text())["seconds"] for p in run_dir.glob("e[0-9][0-9].json")
    )
    metrics["ingestion_seconds_p50"] = median(durations) if durations else None
    metrics["ingestion_seconds_p95"] = (
        durations[math.ceil(len(durations) * 0.95) - 1] if durations else None
    )
    metrics["sdk_calls"] = len(calls)
    metrics["provider_reported_tokens"] = tokens
    metrics["calls_without_token_usage"] = sum(c.get("usage") is None for c in calls)
    (run_dir / "metrics.json").write_text(json.dumps(metrics, indent=2) + "\n")
    lines = [
        "# Graphiti: resultado do experimento",
        "",
        f"Variante: {manifest['variant']}. Execução: {manifest['status']}.",
        f"Projeto: `{manifest['settings']['project']}`. Modelo: `{manifest['settings']['model']}`.",
        f"Invocações ao SDK: {len(calls)}; tokens informados pelo provedor: {tokens}.",
        "Retries internos do SDK e custo monetário não são inferidos desses contadores.",
        "",
        "## Observações automáticas",
        "",
        "```json",
        json.dumps(observations, ensure_ascii=False, indent=2),
        "```",
        "",
        "## Métricas e revisão semântica",
        "",
        "```json",
        json.dumps(metrics, ensure_ascii=False, indent=2),
        "```",
        "",
        "`review.json` contém perguntas, respostas esperadas e caminhos dos resultados.",
        "Marque acerto, fatos corretos/incorretos e fatos esperados recuperados após ler as fontes.",
        "Referência a episódio não comprova citação literal; ausência do codinome não prova ACL.",
        "A revisão dos casos não substitui os gates de identidade, tempo, evidência e governança do ADR.",
        "Os casos de aprovação e ACL têm lacunas na API inspecionada (capabilities.json).",
        "",
    ]
    (run_dir / "report.md").write_text("\n".join(lines), encoding="utf-8")
    return run_dir / "report.md"
