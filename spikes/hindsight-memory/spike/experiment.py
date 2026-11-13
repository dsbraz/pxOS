"""Experimento reproduzível via API pública. Gabaritos nunca entram na ingestão."""

import argparse
import json
import os
import time
import uuid
from pathlib import Path
from urllib.parse import quote

import httpx

from spike.settings import API_URL, ROOT, keys

LABELS = [
    {
        "key": "pessoa",
        "type": "map",
        "description": "Pessoas explicitamente mencionadas; não inferir identidade em menções ambíguas.",
        "fields": {
            k: {"type": "text", "description": d}
            for k, d in {
                "nome": "Nome literal",
                "identificador": "Identificador explícito da pessoa na fonte, se existir",
                "email": "Email literal da pessoa",
                "organizacao": "Organização explicitamente associada à pessoa",
            }.items()
        },
    },
    *[
        {
            "key": k,
            "type": "map",
            "description": d,
            "fields": {
                "nome": {"type": "text"},
                "identificador": {"type": "text", "description": "Código explícito na fonte"},
            },
        }
        for k, d in [
            ("organizacao", "Organizações"),
            ("projeto", "Projetos"),
            ("compromisso", "Compromissos"),
        ]
    ],
]


def memory_item(episode):
    return {
        "content": episode["text"],
        "timestamp": episode["reference_time"],
        "document_id": episode["source_id"],
        "tags": ["access:" + episode["access"]],
        "metadata": {
            "source_id": episode["source_id"],
            "version": str(episode["version"]),
            "received_order": str(episode["received_order"]),
        },
    }


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


class Experiment:
    def __init__(self, bank, directory, resume=False):
        if not bank.startswith("pxos-hs-"):
            raise ValueError("Banco fora do spike")
        self.bank = bank
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=resume)
        self.client = httpx.Client(base_url=API_URL, timeout=600)
        self.timings = json.loads((self.directory / "timings.json").read_text()) if resume else []

    def call(self, method, route="", principal="admin", body=None, params=None, allow_error=False):
        start = time.monotonic()
        result = self.client.request(
            method,
            f"/v1/default/banks/{self.bank}" + route,
            headers={"Authorization": "Bearer " + keys()[principal]},
            json=body,
            params=params,
        )
        self.timings.append(
            {
                "method": method,
                "route": route,
                "principal": principal,
                "seconds": round(time.monotonic() - start, 3),
                "status": result.status_code,
            }
        )
        save(self.directory / "timings.json", self.timings)
        if not allow_error:
            result.raise_for_status()
        return {"status": result.status_code, "body": result.json()}

    def settle(self):
        deadline = time.monotonic() + 600
        while time.monotonic() < deadline:
            operations = self.call("GET", "/operations", params={"limit": 100})["body"][
                "operations"
            ]
            failed = [o for o in operations if o["status"] in ("failed", "cancelled")]
            if failed:
                save(self.directory / "failed-operations.json", failed)
                raise RuntimeError("Operação assíncrona falhou; consultar failed-operations.json")
            if not any(o["status"] in ("pending", "processing") for o in operations):
                return
            time.sleep(2)
        raise TimeoutError("Consolidação não terminou em 600s")

    def snapshot(self, name, principal="admin"):
        result = {}
        for kind, route in [("memories", "/memories/list"), ("entities", "/entities")]:
            first = self.call("GET", route, principal, params={"limit": 100, "offset": 0})["body"]
            field = "items"
            # Fail visibly if the API changes its response shape.
            items = first[field]
            while len(items) < first["total"]:
                page = self.call(
                    "GET", route, principal, params={"limit": 100, "offset": len(items)}
                )["body"][field]
                if not page:
                    raise RuntimeError("Paginação incompleta")
                items.extend(page)
            result[kind] = items
        save(self.directory / (name + ".json"), result)
        return result

    def ask(self, question, principal="admin", extra=None):
        prompt = question["question"]
        if question.get("valid_at"):
            prompt += " Data de referência da pergunta: " + question["valid_at"] + "."
        prompt += " Responda em português com base nas fontes; sinalize ambiguidades e retificações relevantes."
        recall = {
            "query": prompt,
            "budget": "mid",
            "max_tokens": 4096,
            "query_timestamp": question.get("valid_at", "2026-01-13T00:00:00Z"),
        }
        reflect = {"query": prompt, "budget": "mid", "max_tokens": 2048, "include": {"facts": {}}}
        if extra:
            recall.update(extra)
            reflect.update(extra)
        return {
            "recall": self.call("POST", "/memories/recall", principal, recall),
            "reflect": self.call("POST", "/reflect", principal, reflect),
        }

    def run(self, variant):
        episodes = json.loads((ROOT / "fixtures/episodes.json").read_text())
        questions = json.loads((ROOT / "fixtures/queries.json").read_text())
        save(
            self.directory / "manifest.json",
            {
                "bank": self.bank,
                "variant": variant,
                "backend": "managed AlloyDB",
                "hindsight": "1.2.1",
                "labels": LABELS if variant == "labels" else None,
            },
        )
        self.call("PUT", body={})
        if variant == "labels":
            self.call(
                "PATCH",
                "/config",
                body={"updates": {"entity_labels": LABELS, "entities_allow_free_form": True}},
            )
        save(self.directory / "config.json", self.call("GET", "/config"))
        for episode in episodes:
            print(self.bank, "retain", episode["id"], flush=True)
            save(
                self.directory / ("retain-" + episode["id"] + ".json"),
                self.call("POST", "/memories", body={"items": [memory_item(episode)]}),
            )
            self.settle()
            if episode["id"] == "e09":
                self.snapshot("before-correction")
                save(self.directory / "answer-before-correction.json", self.ask(questions[5]))
        snapshot = self.snapshot("after-ingestion")
        identities = {}
        for entity in snapshot["entities"]:
            if (
                "ana" in entity["canonical_name"].lower()
                or "pessoa:" in entity["canonical_name"].lower()
            ):
                identities[entity["id"]] = {
                    "entity": entity,
                    "memories": self.call(
                        "GET", "/memories/list", params={"entity_id": entity["id"], "limit": 1000}
                    )["body"],
                }
        save(self.directory / "identity-links.json", identities)
        for question in questions:
            print(self.bank, "query", question["id"], flush=True)
            principal = "public" if question.get("principal") else "admin"
            save(
                self.directory / ("answer-" + question["id"] + ".json"),
                self.ask(question, principal),
            )
        # Positive control and caller-controlled tag escalation attempt.
        save(self.directory / "restricted-admin.json", self.ask(questions[6]))
        save(
            self.directory / "restricted-forged-tags.json",
            self.ask(questions[6], "public", {"tags": ["access:restricted"], "tags_match": "any"}),
        )
        self.snapshot("public-snapshot", "public")
        routes = [
            "/graph",
            "/entities/graph",
            "/documents/" + quote("synthetic:e08", safe=""),
            "/documents/" + quote("synthetic:e08", safe="") + "/chunks",
        ]
        save(
            self.directory / "public-routes.json",
            {r: self.call("GET", r, "public", allow_error=True) for r in routes},
        )
        save(
            self.directory / "public-retain-denied.json",
            self.call(
                "POST",
                "/memories",
                "public",
                {"items": [memory_item(episodes[0])]},
                allow_error=True,
            ),
        )
        # Replaying the same stable source identifier is distinct from a new document.
        self.snapshot("before-replay")
        save(
            self.directory / "replay.json",
            self.call("POST", "/memories", body={"items": [memory_item(episodes[0])]}),
        )
        self.settle()
        self.snapshot("after-replay")
        save(
            self.directory / "delete.json",
            self.call("DELETE", "/documents/" + quote("synthetic:e08", safe="")),
        )
        self.finish_delete()

    def finish_delete(self):
        questions = json.loads((ROOT / "fixtures/queries.json").read_text())
        if not (self.directory / "delete.json").exists():
            raise ValueError("A fonte ainda não foi excluída")
        self.settle()
        self.snapshot("after-delete")
        save(self.directory / "restricted-after-delete.json", self.ask(questions[6]))
        save(self.directory / "shared-after-delete.json", self.ask(questions[3]))
        save(self.directory / "complete.json", {"complete": True})
        print(self.bank, "complete", flush=True)

    def purge(self):
        import asyncio

        from spike.audit import inspect

        self.call("PUT", body={})
        episodes = json.loads((ROOT / "fixtures/episodes.json").read_text())
        questions = json.loads((ROOT / "fixtures/queries.json").read_text())
        for episode in (episodes[6], episodes[7]):
            print(self.bank, "retain", episode["id"], flush=True)
            save(
                self.directory / ("retain-" + episode["id"] + ".json"),
                self.call("POST", "/memories", body={"items": [memory_item(episode)]}),
            )
            self.settle()
        save(self.directory / "restricted-admin.json", self.ask(questions[6]))
        save(
            self.directory / "public-traces.json",
            self.call("GET", "/llm-requests", "public", allow_error=True),
        )
        self.snapshot("before-delete")
        save(self.directory / "storage-before.json", asyncio.run(inspect(self.bank)))
        save(
            self.directory / "delete.json",
            self.call("DELETE", "/documents/" + quote("synthetic:e08", safe="")),
        )
        self.settle()
        self.snapshot("after-delete")
        save(self.directory / "restricted-after-delete.json", self.ask(questions[6]))
        save(self.directory / "shared-after-delete.json", self.ask(questions[3]))
        save(self.directory / "storage-after.json", asyncio.run(inspect(self.bank)))
        save(
            self.directory / "probe-complete.json",
            {
                "complete": True,
                "delete_traces_with_document": True,
                "llm_trace_enabled": os.getenv("HINDSIGHT_API_LLM_TRACE_ENABLED"),
            },
        )
        print(self.bank, "purge probe complete", flush=True)

    def review(self):
        self.call("PUT", body={})
        episode = json.loads((ROOT / "fixtures/episodes.json").read_text())[0]
        save(
            self.directory / "retain.json",
            self.call("POST", "/memories", body={"items": [memory_item(episode)]}),
        )
        self.settle()
        self.snapshot("after-review")
        save(
            self.directory / "document.json",
            self.call(
                "GET", "/documents/" + quote(episode["source_id"], safe=""), allow_error=True
            ),
        )
        save(
            self.directory / "dry-run.json",
            self.call(
                "POST",
                "/memories/dry-run-extract",
                body={"content": episode["text"], "timestamp": episode["reference_time"]},
                allow_error=True,
            ),
        )
        self.snapshot("after-dry-run")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--variant", choices=["generic", "labels", "review", "purge"], default="generic"
    )
    parser.add_argument("--output", type=Path, default=ROOT / "runs")
    parser.add_argument(
        "--finish-delete", help="Retoma somente a verificação após uma exclusão já realizada"
    )
    args = parser.parse_args()
    if args.finish_delete:
        experiment = Experiment(args.finish_delete, args.output / args.finish_delete, resume=True)
        try:
            experiment.finish_delete()
        finally:
            experiment.client.close()
        return
    bank = f"pxos-hs-{args.variant}-" + uuid.uuid4().hex[:12]
    experiment = Experiment(bank, args.output / bank)
    try:
        if args.variant == "purge":
            experiment.purge()
        elif args.variant == "review":
            experiment.review()
        else:
            experiment.run(args.variant)
    finally:
        experiment.client.close()


if __name__ == "__main__":
    main()
