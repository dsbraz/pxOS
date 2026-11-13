"""Auditoria somente leitura de resíduos por banco após exclusão da fonte."""

import argparse
import asyncio
import json

import asyncpg

from spike.settings import ROOT, configure


async def inspect(bank):
    if not bank.startswith("pxos-hs-"):
        raise ValueError("Banco fora do spike")
    connection = await asyncpg.connect(configure())
    try:
        tables = await connection.fetch(
            "SELECT table_name FROM information_schema.columns "
            "WHERE table_schema='public' AND column_name='bank_id' ORDER BY table_name"
        )
        result = {"bank": bank, "residues": {}, "rls": []}
        async with connection.transaction(readonly=True):
            for table in tables:
                name = table["table_name"]
                identifier = '"' + name.replace('"', '""') + '"'
                count = await connection.fetchval(
                    f"SELECT count(*) FROM public.{identifier} t WHERE bank_id=$1 "
                    "AND lower(to_jsonb(t)::text) LIKE ANY($2::text[])",
                    bank,
                    [
                        "%sigilo-orquidea-731%",
                        "%cancelamento%financiamento%",
                        "%funding%cancell%",
                        "%cancell%funding%",
                    ],
                )
                if count:
                    result["residues"][name] = count
            result["rls"] = [
                dict(r)
                for r in await connection.fetch(
                    "SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class "
                    "WHERE relnamespace='public'::regnamespace AND relname IN ('memory_units','entities','documents','chunks')"
                )
            ]
        return result
    finally:
        await connection.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("bank")
    args = parser.parse_args()
    result = asyncio.run(inspect(args.bank))
    directory = ROOT / "runs" / args.bank
    (directory / "storage-audit.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
