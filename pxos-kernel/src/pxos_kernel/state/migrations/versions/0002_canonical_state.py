"""Governed canonical state: proposal -> review -> fact, with outbox and RLS (PXOS-7, PXOS-50).

The database is the guardian (ADR 0003 §2):
- the application role may only INSERT proposals and reviews and SELECT what RLS allows;
- the reviewer is the session actor, the approver role comes from the registered package,
  self-approval (also through delegation) is refused, and the reviewed digest must match;
- facts and outbox rows are written only by owner functions, never by the application;
- nothing in the canonical tables can be updated or deleted by the application.
"""

from alembic import op

revision = "0002"
down_revision = "0001"

STATEMENTS = [
    # Registered packages, written by the owner when the composition root installs them.
    """
    CREATE TABLE pxos.packages (
        name text PRIMARY KEY,
        version text NOT NULL,
        digest text NOT NULL
    )
    """,
    """
    CREATE TABLE pxos.package_actions (
        package text NOT NULL,
        digest text NOT NULL,
        action text NOT NULL,
        creates text NOT NULL,
        approver_role text NOT NULL,
        PRIMARY KEY (package, digest, action)
    )
    """,
    """
    CREATE TABLE pxos.type_readers (
        package text NOT NULL,
        type_name text NOT NULL,
        role text NOT NULL,
        PRIMARY KEY (package, type_name, role)
    )
    """,
    """
    CREATE TABLE pxos.proposals (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        package text NOT NULL,
        package_version text NOT NULL,
        package_digest text NOT NULL,
        action text NOT NULL,
        type_name text NOT NULL,
        entity_id uuid NOT NULL,
        base_revision integer NOT NULL CHECK (base_revision >= 0),
        operation text NOT NULL CHECK (operation IN ('assert', 'invalidate')),
        valid_from timestamptz NOT NULL,
        valid_to timestamptz CHECK (valid_to > valid_from),
        payload jsonb NOT NULL,
        evidence jsonb NOT NULL CHECK (
            evidence ?& ARRAY['source', 'quote', 'context_ref']
            AND evidence->>'source' <> '' AND evidence->>'quote' <> ''
            AND evidence->>'context_ref' <> ''
        ),
        digest text NOT NULL,
        author text NOT NULL REFERENCES pxos.actors,
        author_principal text NOT NULL REFERENCES pxos.actors,
        created_at timestamptz NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE TABLE pxos.reviews (
        proposal_id uuid PRIMARY KEY REFERENCES pxos.proposals,
        decision text NOT NULL CHECK (decision IN ('approved', 'rejected')),
        reason text CHECK (decision = 'approved' OR coalesce(reason, '') <> ''),
        proposal_digest text NOT NULL,
        reviewer text NOT NULL REFERENCES pxos.actors,
        reviewer_principal text NOT NULL REFERENCES pxos.actors,
        decided_at timestamptz NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE TABLE pxos.facts (
        entity_id uuid NOT NULL,
        revision integer NOT NULL CHECK (revision > 0),
        package text NOT NULL,
        type_name text NOT NULL,
        operation text NOT NULL,
        payload jsonb NOT NULL,
        evidence jsonb NOT NULL,
        valid_from timestamptz NOT NULL,
        valid_to timestamptz,
        proposal_id uuid NOT NULL UNIQUE REFERENCES pxos.proposals,
        known_at timestamptz NOT NULL DEFAULT now(),
        PRIMARY KEY (entity_id, revision)
    )
    """,
    """
    CREATE TABLE pxos.outbox (
        id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        event_type text NOT NULL,
        entity_id uuid NOT NULL,
        payload jsonb NOT NULL,
        created_at timestamptz NOT NULL DEFAULT now(),
        published_at timestamptz
    )
    """,
    # Author is always the session actor, whatever the application sends.
    """
    CREATE FUNCTION pxos.proposal_guard() RETURNS trigger
    LANGUAGE plpgsql SET search_path = pxos, pg_temp AS $$
    BEGIN
        NEW.author := current_actor();
        NEW.author_principal := current_principal();
        NEW.created_at := now();
        IF NOT EXISTS (
            SELECT FROM packages WHERE name = NEW.package AND digest = NEW.package_digest
        ) THEN
            RAISE EXCEPTION 'package % is not registered with this digest', NEW.package
                USING ERRCODE = 'PX012';
        END IF;
        IF NOT EXISTS (
            SELECT FROM package_actions
            WHERE package = NEW.package AND digest = NEW.package_digest
              AND action = NEW.action AND creates = NEW.type_name
        ) THEN
            RAISE EXCEPTION 'action % does not create %', NEW.action, NEW.type_name
                USING ERRCODE = 'PX014';
        END IF;
        RETURN NEW;
    END $$
    """,
    """
    CREATE TRIGGER proposal_guard BEFORE INSERT ON pxos.proposals
    FOR EACH ROW EXECUTE FUNCTION pxos.proposal_guard()
    """,
    # Reviewer is the session actor; the approver role comes from the registered package.
    """
    CREATE FUNCTION pxos.review_guard() RETURNS trigger
    LANGUAGE plpgsql SET search_path = pxos, pg_temp AS $$
    DECLARE
        proposal proposals%ROWTYPE;
        approver text;
    BEGIN
        NEW.reviewer := current_actor();
        NEW.reviewer_principal := current_principal();
        NEW.decided_at := now();
        SELECT * INTO proposal FROM proposals WHERE id = NEW.proposal_id;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'reviewer cannot read proposal %', NEW.proposal_id
                USING ERRCODE = 'PX013';
        END IF;
        IF NEW.proposal_digest <> proposal.digest THEN
            RAISE EXCEPTION 'reviewed digest does not match the proposal'
                USING ERRCODE = 'PX010';
        END IF;
        IF NEW.reviewer IN (proposal.author, proposal.author_principal)
           OR NEW.reviewer_principal IN (proposal.author, proposal.author_principal) THEN
            RAISE EXCEPTION 'the author cannot review their own proposal'
                USING ERRCODE = 'PX011';
        END IF;
        IF NOT EXISTS (
            SELECT FROM packages
            WHERE name = proposal.package AND digest = proposal.package_digest
        ) THEN
            RAISE EXCEPTION 'package % changed after the proposal', proposal.package
                USING ERRCODE = 'PX012';
        END IF;
        SELECT approver_role INTO STRICT approver FROM package_actions
        WHERE package = proposal.package AND digest = proposal.package_digest
          AND action = proposal.action;
        IF NOT EXISTS (
            SELECT FROM actor_roles
            WHERE actor_id = NEW.reviewer_principal AND role = approver
        ) THEN
            RAISE EXCEPTION 'reviewer lacks the approver role %', approver
                USING ERRCODE = 'PX013';
        END IF;
        RETURN NEW;
    END $$
    """,
    """
    CREATE TRIGGER review_guard BEFORE INSERT ON pxos.reviews
    FOR EACH ROW EXECUTE FUNCTION pxos.review_guard()
    """,
    # Owner function: the application has no INSERT on facts or outbox.
    """
    CREATE FUNCTION pxos.review_record() RETURNS trigger
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
                jsonb_build_object('proposal_id', proposal.id, 'reason', NEW.reason)
            );
        END IF;
        RETURN NEW;
    END $$
    """,
    """
    CREATE TRIGGER review_record AFTER INSERT ON pxos.reviews
    FOR EACH ROW EXECUTE FUNCTION pxos.review_record()
    """,
    """
    CREATE FUNCTION pxos.proposal_record() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = pxos, pg_temp AS $$
    BEGIN
        INSERT INTO outbox (event_type, entity_id, payload) VALUES (
            'proposal.created', NEW.entity_id,
            jsonb_build_object(
                'proposal_id', NEW.id, 'package', NEW.package, 'action', NEW.action
            )
        );
        RETURN NEW;
    END $$
    """,
    """
    CREATE TRIGGER proposal_record AFTER INSERT ON pxos.proposals
    FOR EACH ROW EXECUTE FUNCTION pxos.proposal_record()
    """,
    "REVOKE ALL ON FUNCTION pxos.proposal_guard(), pxos.review_guard(), "
    "pxos.review_record(), pxos.proposal_record() FROM PUBLIC",
    # Grants: append-only for the application, nothing destructive anywhere.
    "GRANT SELECT ON pxos.packages, pxos.package_actions, pxos.type_readers TO pxos_app",
    "GRANT SELECT, INSERT ON pxos.proposals, pxos.reviews TO pxos_app",
    "GRANT SELECT ON pxos.facts TO pxos_app",
    # Row-level security on the canonical tables, forced also for the table owner.
    "ALTER TABLE pxos.proposals ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE pxos.proposals FORCE ROW LEVEL SECURITY",
    "ALTER TABLE pxos.reviews ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE pxos.reviews FORCE ROW LEVEL SECURITY",
    "ALTER TABLE pxos.facts ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE pxos.facts FORCE ROW LEVEL SECURITY",
    """
    CREATE FUNCTION pxos.can_read(package_name text, type text) RETURNS boolean
    LANGUAGE sql STABLE SET search_path = pxos, pg_temp AS $$
        SELECT EXISTS (
            SELECT FROM type_readers
            WHERE package = package_name AND type_name = type AND has_role(role)
        )
    $$
    """,
    "REVOKE ALL ON FUNCTION pxos.can_read(text, text) FROM PUBLIC",
    "GRANT EXECUTE ON FUNCTION pxos.can_read(text, text) TO pxos_app",
    """
    CREATE POLICY proposals_read ON pxos.proposals FOR SELECT USING (
        pxos.can_read(package, type_name)
        OR pxos.current_principal() IN (author, author_principal)
    )
    """,
    "CREATE POLICY proposals_insert ON pxos.proposals FOR INSERT WITH CHECK (true)",
    """
    CREATE POLICY reviews_read ON pxos.reviews FOR SELECT USING (
        EXISTS (SELECT FROM pxos.proposals p WHERE p.id = proposal_id)
    )
    """,
    "CREATE POLICY reviews_insert ON pxos.reviews FOR INSERT WITH CHECK (true)",
    """
    CREATE POLICY facts_read ON pxos.facts FOR SELECT USING (
        pxos.can_read(package, type_name)
    )
    """,
    "CREATE POLICY facts_insert ON pxos.facts FOR INSERT WITH CHECK (true)",
]


def upgrade() -> None:
    for statement in STATEMENTS:
        op.execute(statement)
