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
version = "0.1.0"


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

class ActorKind(str, Enum):
    pessoa_interna = "internal_person"
    pessoa_externa = "external_person"
    agente = "agent"



class Organization(ConfiguredBaseModel):
    name: str = Field(default=..., title="nome")


class Actor(ConfiguredBaseModel):
    """
    Pessoa interna, pessoa externa ou agente.
    """
    name: str = Field(default=..., title="nome")
    actor_kind: ActorKind = Field(default=..., title="tipo de ator")


class Role(ConfiguredBaseModel):
    name: str = Field(default=..., title="nome")


class Event(ConfiguredBaseModel):
    occurred_at: datetime  = Field(default=..., title="ocorreu em")


class Evidence(ConfiguredBaseModel):
    """
    Referência à fonte e trecho literal que sustentam uma proposta.
    """
    source: str = Field(default=..., title="fonte")
    quote: str = Field(default=..., title="trecho")
    context_ref: str = Field(default=..., title="referência de contexto")


# Model rebuild
# see https://pydantic-docs.helpmanual.io/usage/models/#rebuilding-a-model
Organization.model_rebuild()
Actor.model_rebuild()
Role.model_rebuild()
Event.model_rebuild()
Evidence.model_rebuild()
