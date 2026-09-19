-- Resident bands are exact single-year sums, separate from living-population ages.
create table public.population_age (
  adm_cd text not null,
  age_band text not null check (age_band in ('5_9','10_14','15_18')),
  population integer check (population >= 0),
  ref_month date not null check (extract(day from ref_month) = 1),
  source text not null check (length(btrim(source)) > 0),
  source_version text not null check (length(btrim(source_version)) > 0),
  ingested_at timestamptz not null default now(),
  estimated boolean not null default false,
  primary key (adm_cd, age_band),
  constraint population_age_dong_fkey foreign key (adm_cd)
    references public.admin_dongs(adm_cd) deferrable initially deferred
);
create index population_age_source_idx on public.population_age (source);
alter table public.population_age enable row level security;
revoke all on public.population_age from anon, authenticated;
grant select on public.population_age to anon, authenticated;
create policy population_age_read on public.population_age
  for select to anon, authenticated using (true);
comment on table public.population_age is
  'Latest resident month. Exact MOIS single-year sums; NULL is suppressed, not zero. '
  'Use admin_dongs.geom GiST then this primary key for spatial lookups.';
