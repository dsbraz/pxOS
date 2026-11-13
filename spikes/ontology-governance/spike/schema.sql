CREATE TABLE IF NOT EXISTS proposals (
    id uuid PRIMARY KEY,
    package text NOT NULL,
    entity text NOT NULL,
    body jsonb NOT NULL,
    digest text NOT NULL,
    proposed_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE IF NOT EXISTS reviews (
    proposal_id uuid PRIMARY KEY REFERENCES proposals(id),
    reviewer text NOT NULL,
    decision text NOT NULL CHECK (decision IN ('approved', 'rejected')),
    reason text NOT NULL,
    reviewed_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE IF NOT EXISTS facts (
    package text NOT NULL,
    entity text NOT NULL,
    revision integer NOT NULL CHECK (revision > 0),
    proposal_id uuid UNIQUE NOT NULL REFERENCES reviews(proposal_id),
    recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (package, entity, revision)
);
