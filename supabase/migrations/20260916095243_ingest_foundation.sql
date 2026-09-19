-- Supabase CLI 2.72.7 supplies PostgreSQL 17.6 and PostGIS 3.3.7.
create extension if not exists postgis with schema extensions version '3.3.7';

create schema if not exists ingest_private;
revoke all on schema ingest_private from public, anon, authenticated;

create table ingest_private.ingest_runs (
  id bigint generated always as identity primary key,
  source text not null,
  source_version text not null,
  target_table text not null,
  row_count bigint not null check (row_count > 0),
  completed_at timestamptz not null default now()
);

create table public.admin_dongs (
  adm_cd text primary key,
  name text not null,
  geom extensions.geometry(MultiPolygon, 4326) not null,
  source text not null,
  source_version text not null,
  ingested_at timestamptz not null default now(),
  estimated boolean not null default false,
  check (extensions.st_isvalid(geom) and not extensions.st_isempty(geom))
);
create index admin_dongs_geom_idx on public.admin_dongs using gist (geom);
create index admin_dongs_source_idx on public.admin_dongs (source);

create table public.census_blocks (
  tot_reg_cd text primary key,
  name text not null,
  geom extensions.geometry(MultiPolygon, 4326) not null,
  source text not null,
  source_version text not null,
  ingested_at timestamptz not null default now(),
  estimated boolean not null default false,
  check (extensions.st_isvalid(geom) and not extensions.st_isempty(geom))
);
create index census_blocks_geom_idx on public.census_blocks using gist (geom);
create index census_blocks_source_idx on public.census_blocks (source);

create table public.geocode_cache (
  address text not null,
  provider text not null,
  geom extensions.geometry(Point, 4326),
  fetched_at timestamptz not null default now(),
  geocode_failed boolean not null default false,
  source text not null,
  source_version text not null,
  ingested_at timestamptz not null default now(),
  estimated boolean not null default false,
  primary key (address, provider),
  check ((geocode_failed and geom is null) or (not geocode_failed and geom is not null))
);

create table public.candidates (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  geom extensions.geometry(Point, 4326) not null,
  floor integer not null,
  deposit numeric check (deposit >= 0),
  user_rent numeric check (user_rent >= 0),
  management_fee numeric check (management_fee >= 0),
  area_m2 numeric check (area_m2 > 0),
  created_at timestamptz not null default now()
);
create index candidates_user_id_idx on public.candidates (user_id);

alter table public.admin_dongs enable row level security;
alter table public.census_blocks enable row level security;
alter table public.geocode_cache enable row level security;
alter table public.candidates enable row level security;

-- Only normalized public boundaries are exposed read-only to API clients.
revoke all on public.admin_dongs, public.census_blocks from anon, authenticated;
grant select on public.admin_dongs, public.census_blocks to anon, authenticated;
create policy admin_dongs_read on public.admin_dongs for select to anon, authenticated using (true);
create policy census_blocks_read on public.census_blocks for select to anon, authenticated using (true);

-- Cache access remains batch-only until the S3 address-search contract is defined.
revoke all on public.geocode_cache from anon, authenticated;
revoke all on public.candidates from anon, authenticated;
grant select, insert, update, delete on public.candidates to authenticated;
create policy candidates_owner on public.candidates to authenticated
  using ((select auth.uid()) = user_id)
  with check ((select auth.uid()) = user_id);
