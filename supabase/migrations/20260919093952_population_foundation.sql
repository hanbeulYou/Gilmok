-- Expand only: preserve census_blocks and its existing readers/data.
-- CELL_ID is scoped by resolution; current verified source is Korea national grid, 250m.
create table public.population_cells (
  resolution_m smallint not null check (resolution_m > 0),
  cell_id text not null check (length(btrim(cell_id)) > 0),
  geom extensions.geometry(Polygon, 4326) not null,
  boundary_generated boolean not null default false,
  source text not null check (length(btrim(source)) > 0),
  source_version text not null check (length(btrim(source_version)) > 0),
  ingested_at timestamptz not null default now(),
  estimated boolean not null default false,
  primary key (resolution_m, cell_id),
  check (extensions.st_isvalid(geom) and not extensions.st_isempty(geom))
);
create index population_cells_geom_idx on public.population_cells using gist (geom);
create index population_cells_source_idx on public.population_cells (source, resolution_m);
alter table public.population_cells enable row level security;
revoke all on public.population_cells from anon, authenticated;
grant select on public.population_cells to anon, authenticated;
create policy population_cells_read on public.population_cells
  for select to anon, authenticated using (true);

comment on column public.population_cells.boundary_generated is
  'Exact verified grid rule used for a missing source boundary; not population estimation.';
comment on table public.population_cells is
  'EPSG:4326 grid boundaries; living_pop storage awaits the measured capacity decision.';
