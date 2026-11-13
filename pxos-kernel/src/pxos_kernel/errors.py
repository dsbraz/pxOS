"""Root of the kernel error hierarchy (ADR 0003 §7)."""


class PxosError(Exception):
    """Base class for every explicit kernel failure."""
