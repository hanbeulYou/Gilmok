-- Restoration checkpoint and source data commit in the same stage transaction.
create table ingest_private.restore_stages (
    stage text primary key check (stage in
      ('boundaries','population','transit','places','buildings','rent','reference')),
    ordinal smallint not null unique check (ordinal between 1 and 7),
    manifest_sha256 text not null check (manifest_sha256 ~ '^[0-9a-f]{64}$'),
    row_counts jsonb not null check (jsonb_typeof(row_counts) = 'object'),
    table_digests jsonb not null check (jsonb_typeof(table_digests) = 'object'),
    seconds double precision not null check (seconds >= 0),
    completed_at timestamptz not null default clock_timestamp()
);
revoke all on ingest_private.restore_stages from public, anon, authenticated;

-- Rollback: keep committed source data. Remove this private checkpoint table only
-- after a replacement resume mechanism has been verified; do not drop source tables.
