import asyncio
import json
from datetime import datetime, timezone
from uuid import uuid4

from spike.store import as_of, connect, history, propose, review


async def run():
    db = await connect()
    results = {}
    try:
        for package, payload, correction, reviewer in [
            (
                "projects",
                {"owner": "ana", "due": "2026-12-01"},
                {"owner": "bia", "due": "2026-12-03"},
                "project-lead",
            ),
            (
                "support",
                {"assignee": "rui", "priority": "normal"},
                {"assignee": "lia", "priority": "urgent"},
                "support-lead",
            ),
        ]:
            entity = str(uuid4())
            evidence = {
                "source": "fixture:meeting-1",
                "quote": "Registro sintético revisado.",
                "context_ref": "fixture:hindsight-context-1",
            }
            initial = await propose(
                db,
                package,
                entity,
                payload,
                author="agent",
                evidence=evidence,
                valid_from="2026-11-01",
            )
            assert await history(db, package, entity) == []
            await review(
                db,
                initial["id"],
                initial["digest"],
                reviewer=reviewer,
                decision="approved",
                reason="Conferido com a fonte",
            )
            before = datetime.now(timezone.utc)
            corrected = await propose(
                db,
                package,
                entity,
                correction,
                author="agent",
                evidence=evidence,
                valid_from="2026-11-01",
                base_revision=1,
            )
            assert len(await history(db, package, entity)) == 1
            await review(
                db,
                corrected["id"],
                corrected["digest"],
                reviewer=reviewer,
                decision="approved",
                reason="Correção retroativa conferida",
            )
            old = await as_of(db, package, entity, valid_on="2026-11-02", known_at=before)
            current = await as_of(
                db, package, entity, valid_on="2026-11-02", known_at=datetime.now(timezone.utc)
            )
            assert old["body"]["payload"] == payload
            assert current["body"]["payload"] == correction
            results[package] = {"entity": entity, "history": await history(db, package, entity)}
        print(json.dumps(results, indent=2, default=str))
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(run())
