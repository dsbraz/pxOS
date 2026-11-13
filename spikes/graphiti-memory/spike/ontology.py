from spike.generated import (
    Compromisso,
    Organizacao,
    Participacao,
    Pessoa,
    Projeto,
    Responsabilidade,
    Vinculo,
)

ENTITY_TYPES = {c.__name__: c for c in (Pessoa, Organizacao, Projeto, Compromisso)}
EDGE_TYPES = {c.__name__: c for c in (Vinculo, Participacao, Responsabilidade)}
EDGE_TYPE_MAP = {
    ("Pessoa", "Organizacao"): ["Vinculo"],
    ("Pessoa", "Projeto"): ["Participacao"],
    ("Pessoa", "Compromisso"): ["Responsabilidade"],
}


def ontology_arguments(variant):
    if variant == "generic":
        return {}
    if variant != "ontology":
        raise ValueError(f"Variante desconhecida: {variant}")
    return {"entity_types": ENTITY_TYPES, "edge_types": EDGE_TYPES, "edge_type_map": EDGE_TYPE_MAP}
