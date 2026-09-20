-- PR 6 is additive: individual transactions remain exclusively in raw storage.
create table public.legal_dongs (
  code8 text primary key check (code8 ~ '^11680[0-9]{3}$'),
  name text not null unique,
  geom extensions.geometry(MultiPolygon,4326) not null,
  source text not null,
  source_version text not null,
  ingested_at timestamptz not null default now(),
  estimated boolean not null default false check (not estimated),
  check (extensions.st_isvalid(geom) and not extensions.st_isempty(geom))
);
create index legal_dongs_geom_idx on public.legal_dongs using gist(geom);

create table public.commercial_trade_stats (
  legal_dong_code text not null references public.legal_dongs(code8),
  trade_kind text not null check (trade_kind in ('general','collective')),
  aggregation_level text not null check (aggregation_level in ('all_floors','floor')),
  floor integer,
  period_start date not null,
  period_end date not null check (period_end >= period_start),
  median_price_per_m2 numeric not null check (
    median_price_per_m2 > 0 and median_price_per_m2 < 'Infinity'::numeric),
  sample_count integer not null check (sample_count > 0),
  unknown_floor_count integer not null check (
    unknown_floor_count between 0 and sample_count),
  area_basis text not null check (area_basis='building_area'),
  source text not null,
  source_version text not null,
  ingested_at timestamptz not null default now(),
  estimated boolean not null default false check (not estimated),
  check ((aggregation_level='all_floors' and floor is null)
    or (aggregation_level='floor' and floor is not null and unknown_floor_count=0)),
  unique nulls not distinct (
    legal_dong_code,trade_kind,aggregation_level,floor,period_start,period_end)
);

-- A geometry without verified period/code provenance must never provide candidate values.
create table public.rent_areas (
  area_code text primary key,
  area_name text not null,
  level text not null check (level in ('district','region')),
  gu_code text not null check (gu_code='11680'),
  geom extensions.geometry(MultiPolygon,4326) not null,
  valid_from date not null,
  valid_to date not null check (valid_to >= valid_from),
  mapping_verified boolean not null default false,
  mapping_evidence text not null,
  source text not null,
  source_version text not null,
  ingested_at timestamptz not null default now(),
  check (not mapping_verified or length(btrim(mapping_evidence)) > 0),
  check (extensions.st_isvalid(geom) and not extensions.st_isempty(geom))
);
create index rent_areas_geom_idx on public.rent_areas using gist(geom);

create table public.rent_survey (
  area_code text not null references public.rent_areas(area_code),
  building_class text not null check (length(btrim(building_class))>0),
  quarter text not null check (quarter ~ '^[0-9]{4}-Q[1-4]$'),
  rent_per_m2 numeric check (rent_per_m2 >= 0 and rent_per_m2 < 'Infinity'::numeric),
  vacancy_rate numeric check (vacancy_rate between 0 and 100),
  rent_statbl_id text,
  rent_cls_id text,
  vacancy_statbl_id text,
  vacancy_cls_id text,
  source text not null,
  source_version text not null,
  ingested_at timestamptz not null default now(),
  estimated boolean not null default false check (not estimated),
  primary key (area_code,building_class,quarter),
  check (rent_per_m2 is null or (rent_statbl_id is not null and rent_cls_id is not null)),
  check (vacancy_rate is null or (vacancy_statbl_id is not null and vacancy_cls_id is not null))
);
create table ingest_private.rent_snapshots (
  source text primary key,
  source_version text not null,
  report jsonb not null,
  ingested_at timestamptz not null default now()
);

alter table public.legal_dongs enable row level security;
alter table public.commercial_trade_stats enable row level security;
alter table public.rent_areas enable row level security;
alter table public.rent_survey enable row level security;
grant select on public.legal_dongs,public.commercial_trade_stats,
  public.rent_areas,public.rent_survey to anon,authenticated;
revoke insert,update,delete,truncate,references,trigger on public.legal_dongs,
  public.commercial_trade_stats,public.rent_areas,public.rent_survey from anon,authenticated;
create policy legal_dongs_read on public.legal_dongs for select to anon,authenticated using(true);
create policy commercial_trade_stats_read on public.commercial_trade_stats
  for select to anon,authenticated using(true);
create policy rent_areas_read on public.rent_areas for select to anon,authenticated using(true);
create policy rent_survey_read on public.rent_survey for select to anon,authenticated using(true);

create function public.rent_inputs(
  lng double precision, lat double precision, radius_m integer, floor integer default null,
  building_class text default null
) returns jsonb language plpgsql stable security invoker set search_path='' as $$
declare
  point extensions.geometry;
  dong_count integer;
  dong_code text;
  trade jsonb;
  by_type jsonb;
  survey jsonb;
  class_values jsonb;
  output jsonb;
  class_count integer;
begin
  if lng is null or lat is null or radius_m is null
    or not (lng between 124 and 132 and lat between 33 and 39 and radius_m between 1 and 5000)
    or (building_class is not null and length(btrim(building_class))=0) then
    raise exception 'Invalid rent query coordinates, radius or building class';
  end if;
  point := extensions.st_setsrid(extensions.st_makepoint(lng,lat),4326);
  select count(*),min(d.code8) into dong_count,dong_code
    from public.legal_dongs d where extensions.st_covers(d.geom,point);
  if dong_count <> 1 then dong_code := null; end if;

  select jsonb_agg(to_jsonb(t) order by t.sample_count desc,t.trade_kind)
    into by_type from public.commercial_trade_stats t
    where t.legal_dong_code=dong_code and
      ((rent_inputs.floor is null and t.aggregation_level='all_floors') or
       (rent_inputs.floor is not null and t.aggregation_level='floor'
          and t.floor=rent_inputs.floor));
  -- collection sorts ahead of general on ties, making the tie policy deterministic.
  trade := by_type->0;

  with candidates as (
    select r.*,a.level,
      count(*) over(partition by r.building_class,r.quarter,a.level) area_count
    from public.rent_survey r join public.rent_areas a using(area_code)
    where dong_code is not null and a.gu_code=left(dong_code,5)
      and a.mapping_verified and extensions.st_covers(a.geom,point)
      and (rent_inputs.building_class is null or r.building_class=rent_inputs.building_class)
      and (r.rent_per_m2 is not null or r.vacancy_rate is not null)
      and a.valid_from <= make_date(left(r.quarter,4)::int,1+3*(right(r.quarter,1)::int-1),1)
      and a.valid_to >= (make_date(left(r.quarter,4)::int,
        1+3*(right(r.quarter,1)::int-1),1)+interval '3 months'-interval '1 day')::date
  ), latest as (
    select c.*,max(c.quarter) over(partition by c.building_class) newest from candidates c
  ), ranked as (
    select l.*,row_number() over(partition by l.building_class
      order by case l.level when 'district' then 0 else 1 end,l.area_code) rank
    from latest l where l.quarter=l.newest and l.area_count=1
  ) select jsonb_object_agg(ranked.building_class,jsonb_build_object(
    'survey_rent_per_m2',rent_per_m2,'survey_vacancy',vacancy_rate,
    'rent_level',level,'area_code',area_code,'quarter',quarter,
    'building_class',ranked.building_class,'source',source,'source_version',source_version,
    'rent_statbl_id',rent_statbl_id,'rent_cls_id',rent_cls_id,
    'vacancy_statbl_id',vacancy_statbl_id,'vacancy_cls_id',vacancy_cls_id))
    into class_values from ranked where rank=1;

  class_values := coalesce(class_values,'{}'::jsonb);
  select count(*) into class_count from jsonb_object_keys(class_values);
  -- No undocumented preference between office/medium/small/collective surveys.
  if class_count=1 then select value into survey from jsonb_each(class_values); end if;
  output := jsonb_build_object(
    'trade_median_per_m2',case when (trade->>'sample_count')::int >= 5
      then (trade->>'median_price_per_m2')::numeric else null end,
    'trade_building_type',trade->>'trade_kind',
    'trade_sample_count',(trade->>'sample_count')::int,
    'trade_by_building_type',coalesce(by_type,'[]'::jsonb),
    'survey_rent_per_m2',survey->'survey_rent_per_m2',
    'survey_vacancy',survey->'survey_vacancy',
    'rent_level',survey->>'rent_level',
    'survey_building_class',survey->>'building_class',
    'survey_by_building_class',class_values,
    'meta',jsonb_build_object('radius_m',radius_m,'floor',rent_inputs.floor,
      'legal_dong_code',dong_code,'spatial_scope','legal_dong_and_survey_area',
      'trade_missing_reason',case when dong_count=0 then 'outside_coverage'
        when dong_count>1 then 'ambiguous_legal_boundary'
        when trade is null then 'no_samples_for_requested_floor'
        when (trade->>'sample_count')::int < 5 then 'fewer_than_five_samples' else null end,
      'survey_missing_reason',case when dong_count<>1 then 'no_unique_legal_dong'
        when class_count=0 then 'no_verified_district_or_region_data'
        when class_count>1 then 'building_class_required' else null end,
      'estimated',false));
  return output;
end;
$$;
revoke all on function public.rent_inputs(double precision,double precision,integer,integer,text)
  from public;
grant execute on function public.rent_inputs(double precision,double precision,integer,integer,text)
  to anon,authenticated;
