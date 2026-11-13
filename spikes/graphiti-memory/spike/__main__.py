import argparse
import asyncio
import json
import os
from pathlib import Path

# Antes de qualquer import Graphiti.
os.environ["GRAPHITI_TELEMETRY_ENABLED"] = "false"
os.environ.setdefault("SEMAPHORE_LIMIT", "2")

from dotenv import load_dotenv

from spike.config import ROOT, Settings

load_dotenv(ROOT / ".env", override=False)
os.environ["GRAPHITI_TELEMETRY_ENABLED"] = "false"


def main():
    parser = argparse.ArgumentParser(description="Spike isolado Graphiti/LinkML/Neo4j/Vertex")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("generate")
    doctor = commands.add_parser("doctor")
    doctor.add_argument("--live", action="store_true")
    run = commands.add_parser("run", aliases=["ingest"])
    run.add_argument("--variant", choices=["generic", "ontology", "both"], default="both")
    run.add_argument("--repetitions", type=int, choices=range(1, 4), default=3)
    run.add_argument("--output", type=Path, required=True)
    run.add_argument(
        "--reset", action="store_true", help="Limpa somente o banco do Compose do spike"
    )
    search = commands.add_parser("query")
    search.add_argument("question")
    search.add_argument("--valid-at")
    search.add_argument("--known-at")
    search.add_argument("--output", type=Path, required=True)
    result = commands.add_parser("report")
    result.add_argument("directory", type=Path)
    args = parser.parse_args()
    if args.command == "generate":
        from spike.generate import generate

        (ROOT / "spike/generated.py").write_text(generate(), encoding="utf-8")
    elif args.command == "report":
        from spike.evaluate import report

        print(report(args.directory))
    else:
        asyncio.run(execute(args))


async def execute(args):
    from spike.clients import close, connect
    from spike.probes import capabilities
    from spike.storage import dump

    if args.command == "doctor" and not args.live:
        print(json.dumps(capabilities(), ensure_ascii=False, indent=2))
        return
    settings = Settings.load()
    if args.command in ("run", "ingest"):
        from spike.runner import run

        variants = ["generic", "ontology"] if args.variant == "both" else [args.variant]
        if len(variants) * args.repetitions > 1 and not args.reset:
            raise ValueError("Comparações independentes requerem --reset do Neo4j dedicado")
        for repetition in range(1, args.repetitions + 1):
            for variant in variants:
                await run(settings, args.output / f"{variant}-{repetition}", variant, args.reset)
        return
    from spike.storage import now

    directory = (
        ROOT / "runs" / ("doctor-" + now().replace(":", "-"))
        if args.command == "doctor"
        else args.output
    )
    directory.mkdir(parents=True, exist_ok=False)
    graph, clients = await connect(settings, directory / "calls.jsonl")
    try:
        if args.command == "doctor":
            from graphiti_core.prompts.models import Message

            from spike.generated import Pessoa

            answer = await graph.llm_client.generate_response(
                [
                    Message(
                        role="user",
                        content="Pessoa com email ana@alfa.example e identificador P-101",
                    )
                ],
                response_model=Pessoa,
            )
            vector = await graph.embedder.create("Teste sintético de memória pxOS")
            if len(vector) != settings.embedding_dim:
                raise ValueError("Dimensão retornada pelo Vertex diferente da configuração")
            dump(directory / "result.json", {"schema_response": answer, "dimensions": len(vector)})
            print(f"Vertex e schema Pydantic verificados: {directory}")
        else:
            from spike.runner import query

            dump(
                directory / "result.json",
                await query(graph, args.question, args.valid_at, args.known_at),
            )
            print(directory / "result.json")
    finally:
        await close(graph, clients)


if __name__ == "__main__":
    main()
