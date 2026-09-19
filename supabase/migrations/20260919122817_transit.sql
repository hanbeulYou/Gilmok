create table public.transit_stops (
  id text primary key,
  type text not null check (type in ('subway', 'bus')),
  name text not null,
  line text not null,
  geom extensions.geometry(Point, 4326) not null,
  source text not null,
  source_version text not null,
  ingested_at timestamptz not null default now(),
  estimated boolean not null default false,
  check (extensions.st_x(geom) between 124 and 132
         and extensions.st_y(geom) between 33 and 39)
);
create index transit_stops_geography_idx on public.transit_stops
  using gist ((geom::extensions.geography));

create table public.transit_boardings (
  stop_id text not null references public.transit_stops(id),
  hour smallint not null check (hour between 0 and 23),
  boarding double precision check (boarding >= 0 and boarding < 'Infinity'::float8),
  alighting double precision check (alighting >= 0 and alighting < 'Infinity'::float8),
  sample_months smallint not null check (sample_months between 0 and 3),
  period_start date not null,
  period_end date not null check (period_end >= period_start),
  unit text not null default 'persons_per_day' check (unit = 'persons_per_day'),
  source text not null,
  source_version text not null,
  ingested_at timestamptz not null default now(),
  estimated boolean not null default false,
  primary key (stop_id, hour)
);

-- Source coverage is part of the snapshot, including unmapped IDs and missing lines.
create table ingest_private.transit_coverage (
  type text primary key check (type in ('subway', 'bus')),
  report jsonb not null,
  ingested_at timestamptz not null default now()
);
revoke all on ingest_private.transit_coverage from public, anon, authenticated;
alter table public.transit_stops enable row level security;
alter table public.transit_boardings enable row level security;
revoke all on public.transit_stops, public.transit_boardings from anon, authenticated;
grant select on public.transit_stops, public.transit_boardings to anon, authenticated;
create policy transit_stops_read on public.transit_stops
  for select to anon, authenticated using (true);
create policy transit_boardings_read on public.transit_boardings
  for select to anon, authenticated using (true);
