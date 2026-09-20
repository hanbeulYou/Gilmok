-- Additive PR 5 schema. Original source snapshots stay immutable in R2.
create table public.building_registers (
  register_pk text primary key check (register_pk ~ '^[0-9]{1,22}$'),
  pnu text check (pnu ~ '^[0-9]{19}$'),
  name text,
  dong_name text,
  floors_above integer check (floors_above >= 0),
  floors_below integer check (floors_below >= 0),
  height_m double precision check (height_m >= 0 and height_m < 'Infinity'::float8),
  main_use_code text,
  main_use_name text,
  other_use text,
  gross_area double precision check (gross_area >= 0),
  passenger_elevators integer check (passenger_elevators >= 0),
  emergency_elevators integer check (emergency_elevators >= 0),
  use_approval_date text,
  source text not null default 'building_hub_title',
  source_version text not null,
  ingested_at timestamptz not null default now(),
  estimated boolean not null default false
);
create index building_registers_pnu_idx on public.building_registers(pnu);

create table public.building_floors (
  id text primary key,
  source_register_pk text not null,
  register_pk text references public.building_registers(register_pk),
  register_link_status text not null check
    (register_link_status in ('matched','title_missing','pnu_mismatch','unsupported_parcel')),
  pnu text check (pnu ~ '^[0-9]{19}$'),
  floor_kind text,
  floor_kind_name text,
  floor_no integer,
  floor_name text,
  use_code text,
  use_name text,
  other_use text,
  area double precision check (area >= 0),
  main_attached_code text,
  source text not null default 'building_hub_floor',
  source_version text not null,
  ingested_at timestamptz not null default now(),
  estimated boolean not null default false,
  check ((register_pk is not null) = (register_link_status='matched'))
);
create index building_floors_register_idx on public.building_floors(register_pk);

create table public.buildings (
  id text primary key,
  source_id text not null,
  gis_id text,
  pnu text not null check (pnu ~ '^11680[0-9]{14}$'),
  source text not null check (source in ('gis_buildings_shp','vworld_wfs_supplement')),
  source_version text not null,
  source_register_pk text,
  register_pk text references public.building_registers(register_pk),
  register_link_status text not null check (register_link_status in
    ('matched','missing_source_pk','title_not_found','pnu_mismatch','supplemental_unlinked')),
  geom extensions.geometry(MultiPolygon,4326) not null,
  geometry_repaired boolean not null,
  source_height_m double precision check (source_height_m > 0),
  floors_above integer check (floors_above > 0),
  floors_below integer check (floors_below >= 0),
  main_use_code text,
  main_use_name text,
  height_m double precision check (height_m > 0 and height_m < 'Infinity'::float8),
  height_source text not null check (height_source in ('source','floors_estimate','unknown')),
  height_estimated boolean not null,
  estimated boolean generated always as (height_source <> 'source') stored,
  render_height_m double precision generated always as (coalesce(height_m,4.0)) stored,
  ingested_at timestamptz not null default now(),
  check (extensions.st_isvalid(geom) and not extensions.st_isempty(geom)),
  check ((height_source='unknown') = (height_m is null)),
  check (height_estimated = (height_source='floors_estimate')),
  check (height_source <> 'source' or height_m=source_height_m),
  check ((register_pk is not null) = (register_link_status='matched')),
  check (source <> 'vworld_wfs_supplement' or
    (register_pk is null and source_register_pk is null
     and register_link_status='supplemental_unlinked'))
);
create index buildings_geography_idx on public.buildings using gist ((geom::extensions.geography));
create index buildings_register_idx on public.buildings(register_pk);
create index buildings_source_idx on public.buildings(source);

create table ingest_private.building_snapshots (
  scope text primary key check (scope='11680'),
  snapshot_version text not null,
  raw_objects jsonb not null,
  report jsonb not null,
  ingested_at timestamptz not null default now()
);
revoke all on ingest_private.building_snapshots from public,anon,authenticated;

alter table public.buildings enable row level security;
alter table public.building_registers enable row level security;
alter table public.building_floors enable row level security;
revoke all on public.buildings,public.building_registers,public.building_floors
  from anon,authenticated;
grant select on public.buildings,public.building_registers,public.building_floors
  to anon,authenticated;
create policy buildings_read on public.buildings for select to anon,authenticated using (true);
create policy building_registers_read on public.building_registers
  for select to anon,authenticated using (true);
create policy building_floors_read on public.building_floors
  for select to anon,authenticated using (true);

create function public.buildings_in_radius(lng double precision,lat double precision,radius_m integer)
returns jsonb language plpgsql stable security invoker set search_path=''
as $$
declare result jsonb;
begin
  if lng is null or lat is null or radius_m is null
     or not (lng between 124 and 132 and lat between 33 and 39 and radius_m between 1 and 5000)
  then raise exception 'Invalid building query coordinates or radius'; end if;
  with nearby as materialized (
    select b.* from public.buildings b where extensions.st_dwithin(
      b.geom::extensions.geography,
      extensions.st_setsrid(extensions.st_makepoint(lng,lat),4326)::extensions.geography,radius_m)
  ), registers as materialized (
    select r.* from public.building_registers r where r.register_pk in (
      select distinct b.register_pk from nearby b
      where b.source='gis_buildings_shp' and b.register_link_status='matched')
  ), uses as (
    select r.main_use_code,count(*) n from registers r group by r.main_use_code
  ), stats as (
    select count(*) total,
      count(*) filter(where height_source='unknown') unknown,
      count(*) filter(where height_source='floors_estimate') estimated,
      count(*) filter(where source='gis_buildings_shp') primary_count,
      count(*) filter(where source='vworld_wfs_supplement') supplemental_count,
      count(*) filter(where register_link_status='matched') linked_count
    from nearby
  )
  select jsonb_build_object(
    'type','FeatureCollection',
    'features',coalesce((select jsonb_agg(jsonb_build_object(
      'type','Feature','id',b.id,'geometry',extensions.st_asgeojson(b.geom,9)::jsonb,
      'properties',jsonb_build_object(
        'source',b.source,'source_version',b.source_version,'pnu',b.pnu,
        'height_m',b.height_m,'height_source',b.height_source,
        'height_estimated',b.height_estimated,'estimated',b.estimated,
        'render_height_m',b.render_height_m,'occlusion_height_m',b.render_height_m,
        'occlusion_included',true,'floors_above',b.floors_above,
        'register_pk',b.register_pk,'register_link_status',b.register_link_status,
        'geometry_repaired',b.geometry_repaired)) order by b.id) from nearby b),'[]'::jsonb),
    'registry',jsonb_build_object(
      'scope','matched_primary_registers_only',
      'register_count',(select count(*) from registers),
      'main_use_counts',coalesce((select jsonb_object_agg(coalesce(main_use_code,'unknown'),n)
                                 from uses),'{}'::jsonb),
      'passenger_elevators',(select sum(passenger_elevators) from registers),
      'emergency_elevators',(select sum(emergency_elevators) from registers),
      'elevator_known_registers',(select count(*) from registers
        where passenger_elevators is not null and emergency_elevators is not null),
      'floor_rows',(select count(*) from public.building_floors f
                    join registers r on r.register_pk=f.register_pk)),
    'meta',jsonb_build_object('radius_m',radius_m,'total_buildings',s.total,
      'primary_count',s.primary_count,'supplemental_count',s.supplemental_count,
      'linked_buildings',s.linked_count,'unknown_buildings',s.unknown,
      'estimated_buildings',s.estimated,'unknown_ratio',s.unknown::numeric/nullif(s.total,0),
      'confidence',jsonb_build_object('unknown_ratio',s.unknown::numeric/nullif(s.total,0),
        'unknown_count',s.unknown,'occluder_count',s.total)))
  into result from stats s;
  return result;
end;
$$;
revoke all on function public.buildings_in_radius(double precision,double precision,integer)
  from public;
grant execute on function public.buildings_in_radius(double precision,double precision,integer)
  to anon,authenticated;
