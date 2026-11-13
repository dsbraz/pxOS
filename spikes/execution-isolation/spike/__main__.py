import asyncio
import json

from spike.gateway import connect, execute, propose, review


async def run():
    report = {}
    for installation in ("alpha", "beta"):
        actor = await connect(installation, "agent_alice")
        approver = await connect(installation, "lead")
        try:
            report[installation] = []
            for target, params in [
                ("project-private", {"owner": "ana", "due": "2026-12-03"}),
                ("ticket-private", {"assignee": "lia", "priority": "urgent"}),
            ]:
                proposal = await propose(actor, target, params)
                await review(approver, proposal)
                result = await execute(actor, proposal)
                audit = await actor.fetch(
                    "SELECT actor,event,details FROM core.audit WHERE proposal_id=$1 ORDER BY seq",
                    proposal["id"],
                )
                report[installation].append(
                    {
                        "proposal_id": str(proposal["id"]),
                        "result": result,
                        "audit": [dict(row) for row in audit],
                    }
                )
        finally:
            await actor.close()
            await approver.close()
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    asyncio.run(run())
