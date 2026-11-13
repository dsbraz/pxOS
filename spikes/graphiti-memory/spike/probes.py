"""Inventário verificável da API pública; não confundir inspeção com teste de LLM."""

import inspect
from importlib.metadata import version

from graphiti_core import Graphiti
from graphiti_core.edges import EntityEdge
from graphiti_core.search.search_filters import SearchFilters
from graphiti_core.utils.ontology_utils.entity_types_utils import validate_entity_types

from spike.ontology import EDGE_TYPES, ENTITY_TYPES


def capabilities():
    validate_entity_types(ENTITY_TYPES)
    # Falha cedo também para schemas de relações não serializáveis.
    for model in [*ENTITY_TYPES.values(), *EDGE_TYPES.values()]:
        model.model_json_schema()
    methods = sorted(
        name
        for name, obj in inspect.getmembers(Graphiti)
        if not name.startswith("_") and callable(obj)
    )
    return {
        "graphiti_version": version("graphiti-core"),
        "linkml_version": version("linkml"),
        "schema_validation": "passed_local",
        "public_methods": methods,
        "add_episode_signature": str(inspect.signature(Graphiti.add_episode)),
        "search_filters": sorted(SearchFilters.model_fields),
        "edge_fields": sorted(EntityEdge.model_fields),
        "approval": {
            "status": "gap_in_inspected_api",
            "detail": "add_episode processa e grava; não oferece prepare/commit da mutação. "
            "Aprovar o texto antes de reextrair não aprova a mutação exata.",
        },
        "permissions": {
            "status": "gap_in_inspected_api",
            "detail": "Busca não recebe principal/ACL por fonte; filtros não garantem "
            "remoção de informação restrita de resumos derivados.",
        },
        "literal_evidence": {
            "status": "requires_live_review",
            "detail": "Referência ao episódio não é evidência de trecho literal.",
        },
        "identity": {
            "status": "requires_live_review",
            "detail": "Atributo identificador_origem não é garantia de chave de junção.",
        },
    }
