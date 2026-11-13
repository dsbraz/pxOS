"""Apply the kernel migrations with the owner connection."""

from pathlib import Path

from alembic import command
from alembic.config import Config

MIGRATIONS = Path(__file__).resolve().parent / "migrations"


def upgrade(owner_dsn: str) -> None:
    """Migrate to head. ``owner_dsn`` is a postgresql:// URL of the schema owner."""
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS))
    url = owner_dsn.replace("postgresql://", "postgresql+asyncpg://", 1)
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    command.upgrade(config, "head")
