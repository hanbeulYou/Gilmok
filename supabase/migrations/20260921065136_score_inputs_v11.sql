-- User-approved v1.1: observed-cell flow, filtered height quality, address cache.
create table ingest_private.building_address_cache (
 address text primary key, pnu text check(pnu ~ '^11680[0-9]{14}$'),
 geom extensions.geometry(Point,4326),
 status text not null check(status in ('ready','not_found','ambiguous')),
 payload jsonb not null, fetched_at timestamptz not null,
 expires_at timestamptz not null check(expires_at=fetched_at+interval '30 days'),
 source text not null default 'building_hub_address', raw_key text,
 check(status<>'ready' or (pnu is not null and geom is not null))
);
create table ingest_private.building_address_requests (
 address text primary key,
 status text not null default 'pending' check(status in ('pending','processing','done','failed')),
 requested_at timestamptz not null default clock_timestamp(), started_at timestamptz,
 finished_at timestamptz, error_code text
);
revoke all on ingest_private.building_address_cache,ingest_private.building_address_requests
 from public,anon,authenticated;

create function score_internal.normalize_building_address(address text) returns text
language sql immutable security invoker set search_path='' as $$
 select case when a ~ '^([가-힣0-9]+(로|길)) *[0-9]+(-[0-9]+)?$'
   then '서울특별시 강남구 '||regexp_replace(a,'(로|길) *([0-9]+(-[0-9]+)?)$','\1 \2')
  when a ~ '^서울(특별시)? 강남구 [가-힣0-9]+(로|길) *[0-9]+(-[0-9]+)?$'
   then regexp_replace(regexp_replace(a,'^서울 ','서울특별시 '),
          '(로|길) *([0-9]+(-[0-9]+)?)$','\1 \2') end
 from (select regexp_replace(btrim(address),'\s+',' ','g') a) q
$$;

-- External requests remain in /ingest; a cache miss only queues work.
create function score_internal.address_building(address text,requested_floor integer,
 p extensions.geometry) returns jsonb language plpgsql volatile security definer set search_path='' as $$
declare normalized text; c ingest_private.building_address_cache%rowtype;
 state text; data jsonb; uses jsonb;
begin
 normalized:=score_internal.normalize_building_address(address);
 if normalized is null or length(normalized)>200 then
  return jsonb_build_object('status','invalid_address','address',null);
 end if;
 select * into c from ingest_private.building_address_cache x where x.address=normalized;
 if c.expires_at>clock_timestamp() then
  if c.status='ready' then
   select jsonb_agg(v-'floor_kind'-'floor_no' order by ordinal)
    into uses from jsonb_array_elements(c.payload->'floors') with ordinality f(v,ordinal)
    where v->>'floor_kind'=case when requested_floor>0 then '20' else '10' end
      and (v->>'floor_no')::integer=abs(requested_floor);
   data:=(c.payload->'building')||jsonb_build_object('floor_use',uses);
  end if;
  return jsonb_build_object('status',c.status,'address',normalized,'data',data,
   'pnu',c.pnu,'fetched_at',c.fetched_at,'expires_at',c.expires_at,
   'address_distance_m',extensions.st_distance(c.geom::extensions.geography,p::extensions.geography));
 end if;
 insert into ingest_private.building_address_requests(address) values(normalized)
 on conflict(address) do update set status='pending',requested_at=clock_timestamp(),
   started_at=null,finished_at=null,error_code=null
 where building_address_requests.status='done';
 select x.status into state from ingest_private.building_address_requests x where x.address=normalized;
 return jsonb_build_object('status',state,'address',normalized);
end;
$$;

create or replace function score_internal.flow(circle extensions.geometry) returns jsonb
language sql stable security invoker set search_path='' as $$
with cells as materialized (
 select c.resolution_m,c.cell_id,
  extensions.st_area(extensions.st_intersection(extensions.st_transform(c.geom,5186),circle)) /
  nullif(extensions.st_area(extensions.st_transform(c.geom,5186)),0) weight
 from public.population_cells c where c.resolution_m=250
  and c.geom operator(extensions.&&) extensions.st_transform(circle,4326)
  and extensions.st_intersects(c.geom,extensions.st_transform(circle,4326))
), hours as (
 select d.dow_type,h.hour,count(c.cell_id) expected_cells,count(l.total) valid_cells,
  sum(l.total*c.weight) value,
  count(l.total)::numeric/nullif(count(c.cell_id),0) coverage_ratio
 from (values ('weekday'),('weekend')) d(dow_type) cross join generate_series(0,23) h(hour)
 left join cells c on c.weight>0
 left join public.living_pop l on l.resolution_m=c.resolution_m and l.cell_id=c.cell_id
  and l.dow_type=d.dow_type and l.hour=h.hour group by d.dow_type,h.hour
), days as (
 select dow_type,jsonb_build_object('hourly',jsonb_agg(value order by hour),
  'golden_avg_pop',case when count(value) filter(where hour>=15 and hour<22)=7
    then avg(value) filter(where hour>=15 and hour<22) end) data,
  jsonb_build_object('expected_cells',max(expected_cells),
    'valid_cells',jsonb_agg(valid_cells order by hour),
    'coverage_ratio',jsonb_agg(coverage_ratio order by hour)) coverage,
  bool_or(coalesce(coverage_ratio,0)<0.8) low_coverage
 from hours group by dow_type
)
select jsonb_object_agg(dow_type,data)||jsonb_build_object('estimated',true,
 'low_coverage',bool_or(low_coverage),'_coverage',jsonb_object_agg(dow_type,coverage)) from days
$$;

CREATE OR REPLACE FUNCTION score_internal.building(p extensions.geometry, radius_m integer, requested_floor integer)
 RETURNS jsonb
 LANGUAGE sql
 STABLE
 SET search_path TO ''
AS $function$
with nearby as materialized (
 select b.*,extensions.st_area(extensions.st_transform(b.geom,5186)) footprint_area_m2,
 coalesce(nullif(b.main_use_name,''),r.main_use_name,'') ~ '(부속|창고)' excluded_use
 from public.buildings b left join public.building_registers r on r.register_pk=b.register_pk where
  extensions.st_dwithin(b.geom::extensions.geography,p::extensions.geography,radius_m)
), containing as materialized (
 select * from nearby where extensions.st_covers(geom,p)
), selected as (
 select * from containing where (select count(*) from containing)=1
), candidate as (
 select jsonb_build_object('id',b.id,'source',b.source,'register_pk',b.register_pk,
   'floors_above',b.floors_above,'floors_below',b.floors_below,'pnu',b.pnu,'location_basis','footprint',
 'main_use',jsonb_build_object('code',coalesce(b.main_use_code,r.main_use_code),'name',coalesce(b.main_use_name,r.main_use_name),'other_use',r.other_use),'height_m',b.height_m,'height_estimated',b.height_estimated,
   'height_source',b.height_source,'floor_use',f.uses,
   'elevators',jsonb_build_object('passenger',r.passenger_elevators,'emergency',r.emergency_elevators),
   'estimated',b.height_estimated) data
 from selected b left join public.building_registers r on r.register_pk=b.register_pk
 left join lateral (
  select jsonb_agg(jsonb_build_object('use_code',use_code,'use_name',use_name,'other_use',other_use,
   'area_m2',area,'main_attached_code',main_attached_code) order by id) uses
  from public.building_floors where register_pk=b.register_pk and
   floor_kind=case when requested_floor>0 then '20' else '10' end and floor_no=abs(requested_floor)
 ) f on true
), quality as (
 select count(*) observed_total,count(*) filter(where height_source='unknown') observed_unknown,
 count(*) filter(where footprint_area_m2>=30 and not excluded_use) total,
 count(*) filter(where footprint_area_m2>=30 and not excluded_use and height_source='unknown') unknown,
 count(*) filter(where footprint_area_m2<30 or excluded_use) excluded,
 count(*) filter(where (footprint_area_m2<30 or excluded_use) and height_source='unknown') excluded_unknown,
 count(*) filter(where footprint_area_m2<30) excluded_small,
 count(*) filter(where excluded_use) excluded_use from nearby
)
select jsonb_build_object('data',coalesce((select data from candidate),jsonb_build_object(
 'id',null,'source',null,'register_pk',null,'floors_above',null,'floors_below',null,'pnu',null,'location_basis',null,
 'main_use',jsonb_build_object('code',null,'name',null,'other_use',null),'height_m',null,
 'height_estimated',null,'height_source',null,'floor_use',null,
 'elevators',jsonb_build_object('passenger',null,'emergency',null),'estimated',false)),
 'height_quality',jsonb_build_object('radius_m',radius_m,'total_buildings',total,
   'unknown_buildings',unknown,'observed_buildings',observed_total,'observed_unknown_buildings',observed_unknown,
 'excluded_buildings',excluded,'excluded_unknown_buildings',excluded_unknown,'excluded_small_buildings',excluded_small,'excluded_use_buildings',excluded_use,'unknown_ratio',unknown::numeric/nullif(total,0)),
 'reason',case (select count(*) from containing) when 0 then 'no_containing_building'
  when 1 then 'source_or_requested_floor_missing' else 'ambiguous_containing_building' end)
from quality
$function$;
-- Replace the public four-argument entry point with a defaulted address parameter.
-- Moving the existing implementation preserves dependencies and the old aggregation rules.
alter function public.score_inputs(double precision,double precision,integer,integer)
 rename to score_inputs_v1;
alter function public.score_inputs_v1(double precision,double precision,integer,integer)
 set schema score_internal;

create function public.score_inputs(lat double precision,lng double precision,radius_m integer,
 floor integer,address text default null) returns jsonb
language plpgsql volatile security invoker set search_path='' as $$
declare r jsonb; lookup jsonb; b jsonb; missing jsonb; estimated jsonb;
 started timestamptz=clock_timestamp(); lookup_started timestamptz; extra_ms numeric=0;
begin
 r:=score_internal.score_inputs_v1(lat,lng,radius_m,floor);
 lookup:=jsonb_build_object('status','not_requested','address',null);
 if nullif(btrim(address),'') is not null then
  lookup_started:=clock_timestamp();
  if r->'building'->>'register_pk' is null then
   lookup:=score_internal.address_building(address,floor,
    extensions.st_setsrid(extensions.st_makepoint(lng,lat),4326));
   if lookup->>'status'='ready' then r:=jsonb_set(r,'{building}',lookup->'data'); end if;
  else
   lookup:=jsonb_build_object('status','not_needed',
    'address',score_internal.normalize_building_address(address));
  end if;
  extra_ms:=extract(epoch from clock_timestamp()-lookup_started)*1000;
 end if;
 b:=r->'building';
 select coalesce(jsonb_agg(item order by item->>'path'),'[]'::jsonb) into missing from (
  select item from jsonb_array_elements(r->'meta'->'missing_fields') item
   where item->>'path' not like 'building.%'
  union all
  select jsonb_build_object('path',path,'reason',case
   when lookup->>'status'='ready' then 'address_register_field_or_floor_missing'
   when lookup->>'status' in ('pending','processing','failed','ambiguous','not_found','invalid_address')
    then 'building_address_'||(lookup->>'status')
   when b->>'id' is null then 'no_unique_containing_building'
   else 'source_or_requested_floor_missing' end)
  from score_internal.null_paths(jsonb_build_object('building',b))
 ) entries;
 select coalesce(jsonb_agg(item order by item->>'path'),'[]'::jsonb) into estimated
 from jsonb_array_elements(r->'meta'->'estimated_fields') item
 where item->>'path' not like 'building.%' or coalesce((b->>'height_estimated')::boolean,false);
 r:=jsonb_set(r,'{meta,missing_fields}',missing);
 r:=jsonb_set(r,'{meta,estimated_fields}',estimated);
 r:=jsonb_set(r,'{meta,schema_version}','"1.1"');
 r:=jsonb_set(r,'{meta,building_lookup}',jsonb_build_object(
  'status',lookup->'status','address',lookup->'address','pnu',lookup->'pnu',
  'fetched_at',lookup->'fetched_at','expires_at',lookup->'expires_at',
  'address_distance_m',lookup->'address_distance_m'));
 r:=jsonb_set(r,'{meta,sources,building_address}',jsonb_build_object(
  'source','building_hub_address','source_version',lookup->'fetched_at',
  'reference_date',left(lookup->>'fetched_at',10),'date_kind','retrieved_on',
  'period_start',null,'period_end',null,'quarter',null,'ingested_at',lookup->'fetched_at',
  'coverage','exact supplied Gangnam road address','available',lookup->>'status'='ready',
  'unlocated_count',null,'limitations',case when lookup->>'status'='ready'
    then jsonb_build_array('address_based_not_coordinate_inference')
    else jsonb_build_array('address_'||(lookup->>'status')) end));
 r:=jsonb_set(r,'{meta,bundle_ms,building}',to_jsonb(
  (r->'meta'->'bundle_ms'->>'building')::numeric+extra_ms));
 return jsonb_set(r,'{meta,total_ms}',to_jsonb(extract(epoch from clock_timestamp()-started)*1000));
end;
$$;
revoke all on function public.score_inputs(double precision,double precision,integer,integer,text)
 from public;
grant execute on function public.score_inputs(double precision,double precision,integer,integer,text)
 to anon,authenticated;
revoke all on function score_internal.address_building(text,integer,extensions.geometry),
 score_internal.normalize_building_address(text) from public;
grant execute on function score_internal.address_building(text,integer,extensions.geometry),
 score_internal.normalize_building_address(text) to anon,authenticated;
