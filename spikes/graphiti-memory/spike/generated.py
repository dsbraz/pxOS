from __future__ import annotations

import re
import sys
from datetime import (
    date,
    datetime,
    time
)
from decimal import Decimal
from enum import Enum
from typing import (
    Any,
    ClassVar,
    Literal,
    Optional,
    Union
)

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    RootModel,
    SerializationInfo,
    SerializerFunctionWrapHandler,
    field_validator,
    model_serializer
)


metamodel_version = "1.12.0"
version = "None"


class ConfiguredBaseModel(BaseModel):
    model_config = ConfigDict(
        serialize_by_alias = True,
        validate_by_name = True,
        validate_assignment = True,
        validate_default = True,
        extra = "forbid",
        arbitrary_types_allowed = True,
        use_enum_values = True,
        strict = False,
    )





class LinkMLMeta(RootModel):
    root: dict[str, Any] = {}
    model_config = ConfigDict(frozen=True)

    def __getattr__(self, key:str):
        return getattr(self.root, key)

    def __getitem__(self, key:str):
        return self.root[key]

    def __setitem__(self, key:str, value):
        self.root[key] = value

    def __contains__(self, key:str) -> bool:
        return key in self.root


linkml_meta = None


class Pessoa(ConfiguredBaseModel):
    """
    Pessoa física. Homônimos podem ser pessoas distintas. Só una aliases quando a fonte fornecer vínculo explícito. Menção ambígua não prova identidade.
    """
    identificador_origem: Optional[str] = Field(default=None, description="""Identificador explicitamente fornecido pela fonte; nunca inventar.""")
    email: Optional[str] = Field(default=None, description="""Email explicitamente informado; nunca inferir a partir do nome.""")
    aliases: Optional[list[str]] = Field(default=None, description="""Apelidos ou abreviações explicitamente vinculados a esta pessoa.""")


class Organizacao(ConfiguredBaseModel):
    """
    Organização explicitamente mencionada na fonte.
    """
    identificador_origem: Optional[str] = Field(default=None, description="""Identificador informado pela fonte.""")


class Projeto(ConfiguredBaseModel):
    """
    Projeto com nome e código próprios, distinto de uma organização.
    """
    codigo: Optional[str] = Field(default=None, description="""Código de projeto explicitamente informado pela fonte.""")


class Compromisso(ConfiguredBaseModel):
    """
    Entrega ou obrigação identificável cujo responsável e prazo podem mudar.
    """
    codigo: Optional[str] = Field(default=None, description="""Código de compromisso explicitamente informado pela fonte.""")
    prazo: Optional[str] = Field(default=None, description="""Prazo informado, em ISO 8601, sem completar datas ausentes.""")


class Vinculo(ConfiguredBaseModel):
    """
    Pessoa trabalha para uma organização.
    """
    cargo: Optional[str] = Field(default=None, description="""Cargo explicitamente informado, se houver.""")


class Participacao(ConfiguredBaseModel):
    """
    Pessoa participa de um projeto.
    """
    papel: Optional[str] = Field(default=None, description="""Papel explicitamente informado, se houver.""")


class Responsabilidade(ConfiguredBaseModel):
    """
    Pessoa é responsável por um compromisso no intervalo indicado pela fonte.
    """
    prazo: Optional[str] = Field(default=None, description="""Prazo do compromisso no intervalo desta responsabilidade, em ISO 8601.""")


# Model rebuild
# see https://pydantic-docs.helpmanual.io/usage/models/#rebuilding-a-model
Pessoa.model_rebuild()
Organizacao.model_rebuild()
Projeto.model_rebuild()
Compromisso.model_rebuild()
Vinculo.model_rebuild()
Participacao.model_rebuild()
Responsabilidade.model_rebuild()
