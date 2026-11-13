"""BRQ@work scribe (PXOS-56): extraction instructions and the reader of extracted facts."""

import pytest

from brq_at_work.scribe import INSTRUCTIONS, read_commitment
from pxos_kernel.ingestion import Candidate

QUOTE = "Bruno: fechado, eu entrego o protótipo do onboarding até sexta, dia 28."
FACT = (
    "COMPROMISSO | dono=bruno | prazo=2026-11-28 | frente=onboarding-app"
    f' | descrição=Entregar o protótipo do onboarding | trecho="{QUOTE}"'
)


def test_instructions_ask_for_the_verbatim_quote_in_the_reader_format() -> None:
    assert "COMPROMISSO | dono=" in INSTRUCTIONS
    assert "literal" in INSTRUCTIONS


def test_reads_a_commitment_fact() -> None:
    assert read_commitment(FACT) == Candidate(
        action="create_commitment",
        payload={
            "description": "Entregar o protótipo do onboarding",
            "owner": "bruno",
            "due_date": "2026-11-28",
            "work_stream": "onboarding-app",
        },
        quote=QUOTE,
    )


def test_reads_a_fact_embedded_in_extraction_prose() -> None:
    assert read_commitment(f"Na reunião ficou registrado: {FACT}") is not None


@pytest.mark.parametrize(
    "fact",
    [
        "Bruno vai entregar o protótipo até o dia 28.",
        FACT.replace(f' | trecho="{QUOTE}"', ""),
        FACT.replace("dono=bruno", "dono="),
    ],
)
def test_anything_else_is_not_a_commitment(fact: str) -> None:
    assert read_commitment(fact) is None
