-- Add the approved fixed-column snapshot; preserve legacy and grid boundaries.
create table public.living_pop (
  resolution_m smallint not null check (resolution_m > 0),
  cell_id text not null,
  dow_type text not null check (dow_type in ('weekday','weekend')),
  hour smallint not null check (hour between 0 and 23),
  total double precision check (total >= 0 and total < 'Infinity'::double precision),
  age_0_4 double precision check (age_0_4 >= 0 and age_0_4 < 'Infinity'::double precision),
  age_5_9 double precision check (age_5_9 >= 0 and age_5_9 < 'Infinity'::double precision),
  age_10_14 double precision check (age_10_14 >= 0 and age_10_14 < 'Infinity'::double precision),
  age_15_19 double precision check (age_15_19 >= 0 and age_15_19 < 'Infinity'::double precision),
  age_20_29 double precision check (age_20_29 >= 0 and age_20_29 < 'Infinity'::double precision),
  age_30_39 double precision check (age_30_39 >= 0 and age_30_39 < 'Infinity'::double precision),
  age_40_49 double precision check (age_40_49 >= 0 and age_40_49 < 'Infinity'::double precision),
  age_50_59 double precision check (age_50_59 >= 0 and age_50_59 < 'Infinity'::double precision),
  age_60_plus double precision check (age_60_plus >= 0 and age_60_plus < 'Infinity'::double precision),
  sample_days smallint not null check (sample_days >= 0),
  period_start date not null,
  period_end date not null,
  source text not null check (length(btrim(source)) > 0),
  source_version text not null check (length(btrim(source_version)) > 0),
  ingested_at timestamptz not null default now(),
  estimated boolean not null default false,
  primary key (resolution_m,cell_id,dow_type,hour),
  constraint living_pop_cell_fkey foreign key (resolution_m,cell_id)
    references public.population_cells (resolution_m,cell_id)
    deferrable initially deferred,
  check (period_end >= period_start and sample_days <= period_end-period_start+1)
);
-- The PK supports cell lookups after population_cells.geom GiST filtering and FK checks.
alter table public.living_pop enable row level security;
revoke all on public.living_pop from anon, authenticated;
grant select on public.living_pop to anon, authenticated;
create policy living_pop_read on public.living_pop
  for select to anon, authenticated using (true);
comment on column public.living_pop.sample_days is
  'Distinct dates with all observed SPOP dong fragments valid; not a per-age count.';
comment on column public.living_pop.age_0_4 is
  'NULL for OA-22784: the source only exposes a combined 0-9 age band.';
comment on column public.living_pop.age_5_9 is
  'NULL for OA-22784: splitting the combined 0-9 age band is not allowed.';
comment on column public.living_pop.age_15_19 is
  'Use the full 15-19 band as the academy flow input; never estimate a 15-18 subset.';
comment on table public.living_pop is
  'Latest 3-month daily means, fixed coarse age columns. Any suppressed/missing day makes its mean NULL.';
comment on table public.population_cells is
  'EPSG:4326 grid boundaries for living_pop; the verified adapter supports 250m national grid cells.';
