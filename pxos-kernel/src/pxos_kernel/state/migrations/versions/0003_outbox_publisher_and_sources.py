"""Outbox publisher role and ingested sources (PXOS-52, PXOS-54).

- pxos_publisher reads the outbox and marks events published; it sees nothing else;
- event payloads carry identifiers only, so the rejection reason leaves the outbox;
- pxos.sources keeps each ingested source version once; the application may only
  insert, so replaying a source is a no-op and nobody reads raw content through it.
"""

from alembic import op

revision = "0003"
down_revision = "0002"

STATEMENTS = [
    """
    DO $$ BEGIN
        IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'pxos_publisher') THEN
            CREATE ROLE pxos_publisher NOLOGIN NOSUPERUSER NOBYPASSRLS;
        END IF;
    END $$
    """,
    "GRANT USAGE ON SCHEMA pxos TO pxos_publisher",
    "GRANT SELECT, UPDATE (published_at) ON pxos.outbox TO pxos_publisher",
    """
    CREATE OR REPLACE FUNCTION pxos.review_record() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = pxos, pg_temp AS $$
    DECLARE
        proposal proposals%ROWTYPE;
    BEGIN
        SELECT * INTO STRICT proposal FROM proposals WHERE id = NEW.proposal_id;
        IF NEW.decision = 'approved' THEN
            INSERT INTO facts (
                entity_id, revision, package, type_name, operation, payload, evidence,
                valid_from, valid_to, proposal_id
            ) VALUES (
                proposal.entity_id, proposal.base_revision + 1, proposal.package,
                proposal.type_name, proposal.operation, proposal.payload, proposal.evidence,
                proposal.valid_from, proposal.valid_to, proposal.id
            );
            INSERT INTO outbox (event_type, entity_id, payload) VALUES (
                'fact.recorded', proposal.entity_id,
                jsonb_build_object(
                    'proposal_id', proposal.id, 'revision', proposal.base_revision + 1,
                    'package', proposal.package, 'type_name', proposal.type_name,
                    'operation', proposal.operation
                )
            );
        ELSE
            INSERT INTO outbox (event_type, entity_id, payload) VALUES (
                'proposal.rejected', proposal.entity_id,
                jsonb_build_object('proposal_id', proposal.id)
            );
        END IF;
        RETURN NEW;
    END $$
    """,
    """
    CREATE TABLE pxos.sources (
        source text NOT NULL CHECK (source <> ''),
        version text NOT NULL CHECK (version <> ''),
        content text NOT NULL,
        ingested_by text NOT NULL DEFAULT pxos.current_actor(),
        ingested_at timestamptz NOT NULL DEFAULT now(),
        PRIMARY KEY (source, version)
    )
    """,
    "GRANT INSERT (source, version, content) ON pxos.sources TO pxos_app",
]


def upgrade() -> None:
    for statement in STATEMENTS:
        op.execute(statement)
