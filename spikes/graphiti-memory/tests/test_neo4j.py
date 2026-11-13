"""Teste real do filtro temporal no banco; não avalia extração por LLM."""

import asyncio
import os

import pytest
from graphiti_core.driver.driver import GraphProvider
from graphiti_core.search.search_filters import edge_search_filter_query_constructor

from spike.storage import cypher, dedicated_container
from spike.temporal import temporal_filter

pytestmark = [
    pytest.mark.neo4j,
    pytest.mark.skipif(
        os.getenv("SPIKE_TEST_NEO4J") != "1", reason="Use SPIKE_TEST_NEO4J=1 com Compose do spike"
    ),
]


def test_valid_time_and_knowledge_time_on_neo4j():
    async def exercise():
        dedicated_container()
        # Rótulo exclusivo: não limpa dados de execuções do experimento.
        await cypher(
            "CREATE (a:SpikeTemporalTest), (b:SpikeTemporalTest), "
            "(a)-[:SPIKE_TEST {name:'old', valid_at:datetime('2026-01-01T00:00:00Z'), "
            "invalid_at:datetime('2026-01-06T00:00:00Z'), "
            "created_at:datetime('2026-02-01T00:00:00Z'), "
            "expired_at:datetime('2026-02-10T00:00:00Z')}]->(b), "
            "(a)-[:SPIKE_TEST {name:'correction', valid_at:datetime('2026-01-05T00:00:00Z'), "
            "created_at:datetime('2026-02-10T00:00:00Z')}]->(b)"
        )
        try:
            for known, expected in [
                ("2026-02-05T00:00:00+00:00", "old"),
                ("2026-02-11T00:00:00+00:00", "correction"),
            ]:
                filters = temporal_filter("2026-01-05T13:00:00+00:00", known)
                clauses, params = edge_search_filter_query_constructor(filters, GraphProvider.NEO4J)
                rows = await cypher(
                    "MATCH (n:SpikeTemporalTest)-[e:SPIKE_TEST]->(m) WHERE "
                    + " AND ".join(clauses)
                    + " RETURN e.name AS name",
                    **params,
                )
                assert [row["name"] for row in rows] == [expected]
        finally:
            await cypher("MATCH (n:SpikeTemporalTest) DETACH DELETE n")

    asyncio.run(exercise())
