-- Additive S2-1 storage. Existing score_inputs v1.2 and S1 source tables stay intact.
create table public.score_reference_sets (
  preset_id text primary key,
  preset_version text not null,
  snapshot text not null check (snapshot ~ '^[0-9]{8}T[0-9]{6}Z$'),
  computed_at timestamptz not null,
  inputs_schema_version text not null,
  cell_count integer not null check (cell_count > 0),
  source_fingerprint text not null,
  source_versions jsonb not null,
  statistics jsonb not null,
  unique (preset_id, preset_version, snapshot)
);
create table public.score_reference (
  preset_id text not null,
  preset_version text not null,
  snapshot text not null,
  radius_m integer not null check (radius_m in (800,1000)),
  cell_id text not null,
  axis_key text not null check (axis_key ~ '^[a-z][a-z0-9_.]*$'),
  raw_value double precision check (raw_value >= 0 and raw_value < 'Infinity'::double precision),
  computed_at timestamptz not null,
  inputs_schema_version text not null,
  primary key (preset_id, radius_m, cell_id, axis_key),
  foreign key (preset_id, preset_version, snapshot)
    references public.score_reference_sets(preset_id, preset_version, snapshot)
);
create index score_reference_distribution_idx
  on public.score_reference(preset_id, preset_version, radius_m, axis_key, raw_value)
  where raw_value is not null;
alter table public.score_reference enable row level security;
alter table public.score_reference_sets enable row level security;
revoke all on public.score_reference, public.score_reference_sets from anon, authenticated;
grant select on public.score_reference, public.score_reference_sets to anon, authenticated;
create policy score_reference_read on public.score_reference for select to anon, authenticated using (true);
create policy score_reference_sets_read on public.score_reference_sets for select to anon, authenticated using (true);
comment on table public.score_reference is 'Current complete reference snapshot only. Historical inputs, distributions and manifests remain in R2 revisions.';
