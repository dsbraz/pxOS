"""Application role, identities and the session actor (PXOS-50, PXOS-51).

The application connects with a login that is a member of ``pxos_app``: no ownership,
no superuser, no BYPASSRLS. Identity tables are written only by the owner at bootstrap.
"""

from alembic import op

revision = "0001"
down_revision = None

STATEMENTS = [
    """
    DO $$ BEGIN
        IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'pxos_app') THEN
            CREATE ROLE pxos_app NOLOGIN NOSUPERUSER NOBYPASSRLS;
        END IF;
    END $$
    """,
    "CREATE SCHEMA pxos",
    "REVOKE ALL ON SCHEMA pxos FROM PUBLIC",
    "GRANT USAGE ON SCHEMA pxos TO pxos_app",
    """
    CREATE TABLE pxos.actors (
        id text PRIMARY KEY CHECK (id ~ '^[a-z][a-z0-9.-]*$'),
        kind text NOT NULL CHECK (kind IN ('internal_person', 'agent')),
        name text NOT NULL
    )
    """,
    """
    CREATE TABLE pxos.actor_roles (
        actor_id text NOT NULL REFERENCES pxos.actors,
        role text NOT NULL CHECK (role ~ '^[a-z][a-z0-9-]*$'),
        PRIMARY KEY (actor_id, role)
    )
    """,
    """
    CREATE TABLE pxos.delegations (
        agent_id text NOT NULL REFERENCES pxos.actors,
        person_id text NOT NULL REFERENCES pxos.actors,
        PRIMARY KEY (agent_id, person_id)
    )
    """,
    "GRANT SELECT ON pxos.actors, pxos.actor_roles, pxos.delegations TO pxos_app",
    # The actor of the transaction, set by the kernel session with set_config(..., true).
    # A pooled connection returns '' after a previous transaction, so empty means none.
    """
    CREATE FUNCTION pxos.current_actor() RETURNS text
    LANGUAGE plpgsql STABLE SET search_path = pxos, pg_temp AS $$
    DECLARE
        actor text := nullif(current_setting('pxos.actor', true), '');
        principal text := nullif(current_setting('pxos.on_behalf_of', true), '');
    BEGIN
        IF actor IS NULL THEN
            RAISE EXCEPTION 'no actor in session' USING ERRCODE = 'PX001';
        END IF;
        IF NOT EXISTS (SELECT FROM actors WHERE id = actor) THEN
            RAISE EXCEPTION 'unknown actor %', actor USING ERRCODE = 'PX001';
        END IF;
        IF principal IS NOT NULL AND NOT EXISTS (
            SELECT FROM delegations WHERE agent_id = actor AND person_id = principal
        ) THEN
            RAISE EXCEPTION '% has no delegation from %', actor, principal
                USING ERRCODE = 'PX002';
        END IF;
        RETURN actor;
    END $$
    """,
    # Whose permissions apply: the delegating person for an agent acting on their behalf.
    """
    CREATE FUNCTION pxos.current_principal() RETURNS text
    LANGUAGE sql STABLE SET search_path = pxos, pg_temp AS $$
        SELECT coalesce(nullif(current_setting('pxos.on_behalf_of', true), ''), current_actor())
        FROM (SELECT current_actor()) AS checked
    $$
    """,
    """
    CREATE FUNCTION pxos.has_role(wanted text) RETURNS boolean
    LANGUAGE sql STABLE SET search_path = pxos, pg_temp AS $$
        SELECT EXISTS (
            SELECT FROM actor_roles WHERE actor_id = current_principal() AND role = wanted
        )
    $$
    """,
    "REVOKE ALL ON FUNCTION pxos.current_actor(), pxos.current_principal(), "
    "pxos.has_role(text) FROM PUBLIC",
    "GRANT EXECUTE ON FUNCTION pxos.current_actor(), pxos.current_principal(), "
    "pxos.has_role(text) TO pxos_app",
]


def upgrade() -> None:
    for statement in STATEMENTS:
        op.execute(statement)
