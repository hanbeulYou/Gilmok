-- Row-level provenance is intentionally replaced by snapshot metadata for stores.
-- Approved PR 4 contract: exactly six columns, no name/address/KSIC duplication.
create table public.stores (
  store_id text primary key,
  inds_lcls text not null check (inds_lcls ~ '^[A-Z][0-9]$'),
  inds_mcls text not null check (inds_mcls ~ '^[A-Z][0-9]{3}$'),
  inds_scls text not null check (inds_scls ~ '^[A-Z][0-9]{5}$'),
  floor text,
  geom extensions.geometry(Point,4326) not null,
  check (left(inds_mcls,2)=inds_lcls and left(inds_scls,4)=inds_mcls)
);
create index stores_geography_idx on public.stores using gist ((geom::extensions.geography));

create table public.academies (
  id text primary key,
  name text not null,
  institution_type text not null,
  registration_status text not null,
  field text not null,
  affiliation text not null,
  course_list text not null,
  course text not null,
  address text not null,
  geom extensions.geometry(Point,4326),
  geocode_failed boolean not null,
  geocode_provider text,
  geocode_reason text,
  source text not null,
  source_version text not null,
  ingested_at timestamptz not null default now(),
  estimated boolean not null default false,
  check (geocode_failed = (geom is null))
);
create index academies_geography_idx on public.academies
  using gist ((geom::extensions.geography)) where geom is not null;

create table public.schools (
  id text primary key,
  name text not null,
  level text not null check (level in ('elem','mid','high')),
  school_type text not null,
  address text not null,
  geom extensions.geometry(Point,4326),
  geocode_failed boolean not null,
  geocode_provider text,
  geocode_reason text,
  source text not null,
  source_version text not null,
  ingested_at timestamptz not null default now(),
  estimated boolean not null default false,
  check (geocode_failed = (geom is null))
);
create index schools_geography_idx on public.schools
  using gist ((geom::extensions.geography)) where geom is not null;

alter table public.geocode_cache add column failure_reason text;
-- A committed claim survives a crash/timeout. It is never automatically retried.
create table ingest_private.geocode_requests (
  address text not null,
  provider text not null check (provider in ('kakao','vworld')),
  status text not null check (status in ('pending','success','not_found','ambiguous',
                                        'invalid','blocked','unknown')),
  error_code text,
  attempted_at timestamptz not null default now(),
  primary key (address,provider)
);
create index geocode_requests_attempted_idx
  on ingest_private.geocode_requests(provider,attempted_at);

create table ingest_private.place_snapshots (
  target_table text primary key check (target_table in ('stores','academies','schools')),
  source text not null,
  source_version text not null,
  raw_key text not null,
  row_count bigint not null check (row_count > 0),
  located_count bigint not null check (located_count >= 0 and located_count <= row_count),
  estimated boolean not null default false,
  report jsonb not null,
  ingested_at timestamptz not null default now()
);
revoke all on ingest_private.geocode_requests, ingest_private.place_snapshots
  from public, anon, authenticated;

alter table public.stores enable row level security;
alter table public.academies enable row level security;
alter table public.schools enable row level security;
revoke all on public.stores, public.academies, public.schools from anon, authenticated;
grant select on public.stores, public.academies, public.schools to anon, authenticated;
create policy stores_read on public.stores for select to anon, authenticated using (true);
create policy academies_read on public.academies for select to anon, authenticated using (true);
create policy schools_read on public.schools for select to anon, authenticated using (true);
