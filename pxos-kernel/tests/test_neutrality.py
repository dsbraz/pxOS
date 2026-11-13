"""The kernel carries no domain vocabulary (ADR 0002).

Every text file under pxos-kernel/ is scanned for terms of the distribution's domain
and systems. When a gray case is decided in ADR 0002, update this list with it.
"""

import re
from pathlib import Path

KERNEL_ROOT = Path(__file__).resolve().parents[1]

# Distinctive terms match anywhere, so identifiers such as create_commitment or
# CommitmentProposal are caught too.
DOMAIN_SUBSTRINGS = [
    "brq",
    "m365",
    "granola",
    "commitment",
    "workstream",
    "work_stream",
    "meeting",
    "compromisso",
    "frente de trabalho",
    "reuni",
]

# Short terms collide with common words (budget, steams), so they match whole words.
DOMAIN_WORDS = ["bud", "teams"]

PATTERN = re.compile(
    "|".join([re.escape(term) for term in DOMAIN_SUBSTRINGS] + [rf"\b{w}\b" for w in DOMAIN_WORDS]),
    re.IGNORECASE,
)

SKIPPED_PARTS = {"__pycache__", ".venv", ".mypy_cache", ".pytest_cache", ".ruff_cache"}


def kernel_files() -> list[Path]:
    return [
        path
        for path in KERNEL_ROOT.rglob("*")
        if path.is_file()
        and path.resolve() != Path(__file__).resolve()
        and not SKIPPED_PARTS.intersection(path.relative_to(KERNEL_ROOT).parts)
    ]


def test_kernel_has_files_to_scan() -> None:
    assert kernel_files()


def test_kernel_has_no_domain_terms() -> None:
    hits: list[str] = []
    for path in kernel_files():
        relative = path.relative_to(KERNEL_ROOT)
        hits.extend(f"{relative}: {match.group()}" for match in PATTERN.finditer(str(relative)))
        text = path.read_text(encoding="utf-8")
        for number, line in enumerate(text.splitlines(), start=1):
            for match in PATTERN.finditer(line):
                hits.append(f"{relative}:{number}: {match.group()}")
    assert not hits, "Domain terms in the kernel:\n" + "\n".join(hits)
