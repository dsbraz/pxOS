import json
import subprocess
from datetime import UTC, datetime

from neo4j import AsyncGraphDatabase

from spike.config import NEO4J_URI, ROOT, neo4j_password


def dump(path, data):
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8"
    )


def dedicated_container():
    result = subprocess.run(
        ["docker", "compose", "-f", str(ROOT / "compose.yaml"), "ps", "-q", "neo4j"],
        capture_output=True,
        text=True,
        check=True,
    )
    container_id = result.stdout.strip()
    if not container_id or "\n" in container_id:
        raise RuntimeError("Suba somente o Neo4j dedicado com docker compose up -d --wait")
    info = json.loads(
        subprocess.run(
            ["docker", "inspect", container_id], capture_output=True, text=True, check=True
        ).stdout
    )[0]
    labels = info["Config"]["Labels"]
    bindings = info["NetworkSettings"]["Ports"].get("7687/tcp", [])
    if (
        labels.get("com.docker.compose.project") != "pxos-graphiti-spike"
        or labels.get("com.docker.compose.service") != "neo4j"
        or bindings != [{"HostIp": "127.0.0.1", "HostPort": "17687"}]
    ):
        raise RuntimeError("Recusado: container/porta não pertencem ao spike")
    return container_id, info["Image"]


async def cypher(query, **params):
    async with AsyncGraphDatabase.driver(NEO4J_URI, auth=("neo4j", neo4j_password())) as driver:
        result, _, _ = await driver.execute_query(query, parameters_=params, database_="neo4j")
        return [r.data() for r in result]


async def reset():
    dedicated_container()
    await cypher("MATCH (n) DETACH DELETE n")


async def snapshot():
    nodes = await cypher("MATCH (n) RETURN labels(n) AS labels, properties(n) AS properties")
    edges = await cypher(
        "MATCH (n)-[r]->(m) RETURN n.uuid AS source, m.uuid AS target, "
        "type(r) AS type, properties(r) AS properties"
    )
    for row in nodes + edges:
        row["properties"] = {k: v for k, v in row["properties"].items() if "embedding" not in k}
    # Neo4j DateTime is not JSON serializable; preserve ISO dates consistently.
    return json.loads(json.dumps({"nodes": nodes, "edges": edges}, default=str))


def now():
    return datetime.now(UTC).isoformat()
