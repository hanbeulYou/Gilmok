-- Commit the active refresh manifest with the source's data, never before it.
create table ingest_private.refresh_snapshots (
  source text primary key,
  period_end date not null,
  snapshot text not null check(snapshot ~ '^[0-9]{8}T[0-9]{6}Z$'),
  manifest jsonb not null,
  committed_at timestamptz not null default now()
);
revoke all on ingest_private.refresh_snapshots from public, anon, authenticated;
