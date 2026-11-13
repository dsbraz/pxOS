import hashlib
import json
import time
from dataclasses import asdict
from datetime import datetime
from importlib.metadata import version

from graphiti_core.nodes import EpisodeType
from graphiti_core.search.search_config_recipes import COMBINED_HYBRID_SEARCH_RRF

from spike.clients import close, connect
from spike.config import ROOT
from spike.evaluate import SECRET, report, structural_checks
from spike.ontology import ontology_arguments
from spike.probes import capabilities
from spike.storage import cypher, dedicated_container, dump, now, reset, snapshot
from spike.temporal import temporal_filter


def fixtures(name):
    return json.loads((ROOT / "fixtures" / f"{name}.json").read_text())


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


async def add(graph, episode, variant):
    # Metadados são a proveniência da fonte, iguais nas duas variantes, não regras de resolução.
    return await graph.add_episode(
        name=f"{episode['source_id']}@{episode['version']}",
        episode_body=episode["text"],
        source_description=json.dumps(
            {k: episode[k] for k in ("source_id", "version", "access", "participants")},
            ensure_ascii=False,
        ),
        reference_time=datetime.fromisoformat(episode["reference_time"]),
        source=EpisodeType.text,
        **ontology_arguments(variant),
    )


async def query(graph, question, valid_at=None, known_at=None):
    results = await graph.search_(
        question,
        config=COMBINED_HYBRID_SEARCH_RRF.model_copy(deep=True),
        search_filter=temporal_filter(valid_at, known_at),
    )
    result = results.model_dump(mode="json")
    # Embeddings não ajudam a revisão e aumentam muito o artefato.
    for kind in ("nodes", "edges", "episodes", "communities"):
        for item in result.get(kind, []):
            for key in list(item):
                if "embedding" in key:
                    del item[key]
    return result


async def run(settings, directory, variant, clear=False):
    container_id, image = dedicated_container()
    if directory.exists():
        raise ValueError("Diretório de execução já existe; não sobrescrever evidências")
    directory.mkdir(parents=True)
    (directory / "calls.jsonl").touch()
    manifest = {
        "started_at": now(),
        "status": "running",
        "variant": variant,
        "settings": asdict(settings),
        "container": container_id,
        "image": image,
        "graphiti": version("graphiti-core"),
        "linkml": version("linkml"),
        "inputs": {
            str(p.relative_to(ROOT)): digest(p)
            for p in [
                ROOT / "uv.lock",
                ROOT / "ontology/memory.yaml",
                ROOT / "fixtures/episodes.json",
                ROOT / "fixtures/queries.json",
            ]
        },
    }
    dump(directory / "manifest.json", manifest)
    dump(directory / "capabilities.json", capabilities())
    graph, clients = None, []
    observations, review, episode_ids = {}, [], {}
    try:
        # Verificar acesso ao Vertex antes de remover o estado local de uma execução anterior.
        graph, clients = await connect(settings, directory / "calls.jsonl")
        if clear:
            await reset()
        if (await cypher("MATCH (n) RETURN count(n) AS count"))[0]["count"]:
            raise ValueError("Grafo não vazio. Use --reset para limpar apenas o Neo4j do spike")
        await graph.build_indices_and_constraints()
        await graph.driver.execute_query("CALL db.awaitIndexes(120)")
        episodes = fixtures("episodes")
        knowledge_before_correction = None
        for episode in episodes:
            started = time.perf_counter()
            result = await add(graph, episode, variant)
            episode_ids[episode["id"]] = result.episode.uuid
            checkpoint = {
                "episode_id": episode["id"],
                "episode_uuid": result.episode.uuid,
                "ingested_at": now(),
                "seconds": time.perf_counter() - started,
                "expected": episode["expected"],
                "graph": await snapshot(),
            }
            dump(directory / f"{episode['id']}.json", checkpoint)
            dump(directory / "episode_ids.json", episode_ids)
            print(f"{directory.name}: {episode['id']} ({checkpoint['seconds']:.1f}s)", flush=True)
            if episode["id"] == "e09":
                knowledge_before_correction = now()
                dump(
                    directory / "before-correction.json",
                    await query(
                        graph,
                        "Quem era responsável pelo CMP-1 em 5 de janeiro às 13h UTC?",
                        "2026-01-05T13:00:00+00:00",
                        knowledge_before_correction,
                    ),
                )
        state = await snapshot()
        dump(directory / "final-graph.json", state)
        observations["structure"] = structural_checks(state)
        for q in fixtures("queries"):
            answer = await query(graph, q["question"], q.get("valid_at"))
            dump(directory / f"query-{q['id']}.json", answer)
            review.append(
                {
                    **q,
                    "result": f"query-{q['id']}.json",
                    "correct": None,
                    "correct_facts": None,
                    "incorrect_facts": None,
                    "expected_facts": None,
                    "recovered_expected_facts": None,
                    "literal_evidence": None,
                    "notes": "",
                }
            )
            if q["id"] == "restricted":
                observations["permissions"] = {
                    "principal_enforced": False,
                    "secret_in_unfiltered_search": SECRET in json.dumps(answer),
                    "status": "native_api_has_no_principal_authorization",
                }
        dump(
            directory / "after-correction-as-known-before.json",
            await query(
                graph,
                "Quem era responsável pelo CMP-1 em 5 de janeiro às 13h UTC?",
                "2026-01-05T13:00:00+00:00",
                knowledge_before_correction,
            ),
        )
        review.append(
            {
                "id": "bitemporal",
                "correct": None,
                "expected": "Consulta as-known-before deve reproduzir o conhecimento "
                "anterior à retificação, mesmo depois da ingestão dela.",
                "result": ["before-correction.json", "after-correction-as-known-before.json"],
                "notes": "",
            }
        )
        # Replay nativo, sem cache nem UUID inventado, medido após as consultas comparáveis.
        replay = await add(graph, episodes[0], variant)
        replay_state = await snapshot()
        dump(directory / "after-replay.json", replay_state)
        observations["native_replay"] = {
            "same_episode_uuid": replay.episode.uuid == episode_ids["e01"],
            "before_nodes": len(state["nodes"]),
            "after_nodes": len(replay_state["nodes"]),
            "before_edges": len(state["edges"]),
            "after_edges": len(replay_state["edges"]),
        }
        # Remove a fonte restrita: fato compartilhado deve sobreviver, fato exclusivo deve sumir.
        await graph.remove_episode(episode_ids["e08"])
        deleted = await snapshot()
        dump(directory / "after-delete.json", deleted)
        observations["deletion"] = structural_checks(deleted, episode_ids["e08"])
        before_shared = {
            r["properties"]["uuid"]
            for r in replay_state["edges"]
            if r["type"] == "RELATES_TO"
            and episode_ids["e08"] in r["properties"].get("episodes", [])
            and len(r["properties"].get("episodes", [])) > 1
        }
        after_ids = {r["properties"].get("uuid") for r in deleted["edges"]}
        observations["deletion"]["shared_facts_before"] = len(before_shared)
        observations["deletion"]["shared_facts_preserved"] = (
            before_shared <= after_ids if before_shared else None
        )
        review.append(
            {
                "id": "deletion",
                "correct": None,
                "expected": "Apagar risco/codinome exclusivo e manter responsabilidade "
                "apoiada por fontes públicas, inclusive resumos e atributos.",
                "result": ["after-replay.json", "after-delete.json"],
                "notes": "",
            }
        )
        manifest["status"] = "completed_pending_semantic_review"
    except Exception as exc:
        manifest.update(status="error", error_type=type(exc).__name__, error=str(exc))
        raise
    finally:
        manifest["finished_at"] = now()
        dump(directory / "manifest.json", manifest)
        dump(directory / "observations.json", observations)
        dump(directory / "review.json", review)
        report(directory)
        if graph:
            await close(graph, clients)
