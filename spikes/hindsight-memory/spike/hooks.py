"""Política mínima para o experimento usando apenas extensões públicas do Hindsight."""

import json
from dataclasses import asdict

from hindsight_api.engine.search.tags import TagGroupLeaf
from hindsight_api.extensions.operation_validator import (
    MemoryReview,
    OperationValidatorExtension,
    ValidationResult,
)
from hindsight_api.extensions.tenant import (
    AuthenticationError,
    Tenant,
    TenantContext,
    TenantExtension,
)

from spike.settings import ROOT, keys


class SpikeTenant(TenantExtension):
    async def authenticate(self, context):
        if context.api_key not in keys().values():
            raise AuthenticationError("Credencial do spike inválida")
        return TenantContext(schema_name="public")

    async def list_tenants(self):
        return [Tenant(schema="public")]


class SpikePolicy(OperationValidatorExtension):
    async def resolve_tag_scope(self, ctx):
        if ctx.request_context.api_key == keys()["public"]:
            return [TagGroupLeaf(tags=["access:public"], match="any_strict")]
        return None

    async def validate_retain(self, ctx):
        if ctx.request_context.api_key == keys()["public"]:
            return ValidationResult.reject("Leitor do experimento não pode ingerir")
        return ValidationResult.accept()

    async def validate_recall(self, ctx):
        return ValidationResult.accept()

    async def validate_reflect(self, ctx):
        return ValidationResult.accept()

    async def filter_retain_facts(self, ctx):
        if ctx.bank_id.startswith("pxos-hs-review-"):
            path = ROOT / "runs" / "hook-events.jsonl"
            path.parent.mkdir(exist_ok=True)
            with path.open("a") as stream:
                stream.write(
                    json.dumps(
                        {
                            "bank": ctx.bank_id,
                            "document": ctx.document_id,
                            "facts": [asdict(f) for f in ctx.facts],
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
            return [MemoryReview(keep=False) for _ in ctx.facts]
        return None
