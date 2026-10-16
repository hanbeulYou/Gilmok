-- Synthetic tests only: matches the pending G schema; contains no source data.
-- Additive: two private projection tables and their access restrictions only.
-- No existing function/trigger/table/row changes; no automatic data backfill.
create schema if not exists app_private;
create table if not exists app_private.academy_display (
  academy_id text primary key,
  floor_label text,
  floor_status text not null check (floor_status in ('explicit','missing','ambiguous')),
  source_revision text not null,
  raw_sha256 text not null check (raw_sha256 ~ '^[0-9a-f]{64}$'),
  check ((floor_status='explicit') = (floor_label is not null))
);
create table if not exists app_private.academy_display_release (
  singleton boolean primary key default true check (singleton),
  source_revision text not null,
  source_version text not null,
  raw_sha256 text not null check (raw_sha256 ~ '^[0-9a-f]{64}$'),
  row_count integer not null check (row_count > 0),
  coordinate_provider text not null check (coordinate_provider='juso'),
  ingested_at timestamptz not null default now()
);
alter table app_private.academy_display enable row level security;
alter table app_private.academy_display_release enable row level security;
revoke all on app_private.academy_display, app_private.academy_display_release
  from public, anon, authenticated;
comment on table app_private.academy_display is
  'Explicit address floor labels only. Updated strictly with academy source and reference release.';
