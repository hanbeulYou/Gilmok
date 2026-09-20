-- PR 7: one public request, independently aggregated single-row bundles.
create schema score_internal;
revoke all on schema score_internal from public;
grant usage on schema score_internal to anon, authenticated;

-- Preserve the PR 6 implementation and its read permissions behind both entry points.
alter function public.rent_inputs(double precision,double precision,integer,integer,text)
  set schema score_internal;
create function public.rent_inputs(lng double precision, lat double precision,
  radius_m integer, floor integer default null, building_class text default null)
returns jsonb language sql stable security invoker set search_path='' as $$
  select score_internal.rent_inputs(lng,lat,radius_m,floor,building_class)
$$;
revoke all on function public.rent_inputs(double precision,double precision,integer,integer,text) from public;
grant execute on function public.rent_inputs(double precision,double precision,integer,integer,text) to anon,authenticated;

-- This helper exposes an explicit whitelist, never private audit reports or raw objects.
create function score_internal.sources() returns jsonb
language sql stable security definer set search_path='' as $$
with items as (
  select target_table as key, jsonb_build_object(
    'source',source,'source_version',source_version,'reference_date',source_version,
    'date_kind','snapshot','period_start',null,'period_end',null,'quarter',null,
    'ingested_at',ingested_at,'coverage','Seoul','available',true,
    'unlocated_count',row_count-located_count,'limitations',case when row_count>located_count
      then jsonb_build_array('unlocated_records_not_in_spatial_counts') else '[]'::jsonb end) value
  from ingest_private.place_snapshots
  union all
  select 'resident_population', (select jsonb_build_object('source',source,
    'source_version',source_version,'reference_date',ref_month,'date_kind','reference_month',
    'period_start',null,'period_end',null,'quarter',null,'ingested_at',ingested_at,
    'coverage','Seoul','available',true,'unlocated_count',null,'limitations','[]'::jsonb)
    from public.population_age limit 1)
  union all
  select 'admin_boundaries', (select jsonb_build_object('source',source,
    'source_version',source_version,'reference_date',source_version,'date_kind','boundary_version',
    'period_start',null,'period_end',null,'quarter',null,'ingested_at',ingested_at,
    'coverage','Seoul','available',true,'unlocated_count',null,'limitations','[]'::jsonb)
    from public.admin_dongs limit 1)
  union all
  select 'population_grid', (select jsonb_build_object('source',source,
    'source_version',source_version,'reference_date',null,'date_kind','unknown',
    'period_start',null,'period_end',null,'quarter',null,'ingested_at',ingested_at,
    'coverage','Seoul','available',true,'unlocated_count',null,
    'limitations',jsonb_build_array('boundary_reference_date_not_verified')) from public.population_cells limit 1)
  union all
  select 'living_population', (select jsonb_build_object('source',source,
    'source_version',source_version,'reference_date',null,'date_kind','period',
    'period_start',period_start,'period_end',period_end,'quarter',null,'ingested_at',ingested_at,
    'coverage','Seoul','available',true,'unlocated_count',null,
    'limitations',jsonb_build_array('valid_days_mean','age_0_4_and_5_9_not_separable')) from public.living_pop limit 1)
  union all
  select type||'_positions', jsonb_build_object('source','seoul_transit',
    'source_version',report->'coordinates'->'retrieved_on',
    'reference_date',report->'coordinates'->'retrieved_on','date_kind','retrieved_on',
    'period_start',null,'period_end',null,'quarter',null,'ingested_at',ingested_at,
    'coverage','Seoul','available',true,'unlocated_count',null,
    'limitations',jsonb_build_array('historical_positions_unverified') ||
      coalesce(report->'missing_lines','[]'::jsonb)) from ingest_private.transit_coverage
  union all
  select 'transit_counts', (select jsonb_build_object('source',source,
    'source_version',source_version,'reference_date',null,'date_kind','period',
    'period_start',period_start,'period_end',period_end,'quarter',null,'ingested_at',ingested_at,
    'coverage','Seoul','available',true,'unlocated_count',null,
    'limitations',jsonb_build_array('daily_mean_without_weekday_split','unmatched_units_not_imputed'))
    from public.transit_boardings limit 1)
  union all
  select kind.key, (select jsonb_build_object('source',b.source,
    'source_version',b.source_version,'reference_date',b.source_version,
    'date_kind',case when kind.key='building_shp' then 'source_version' else 'retrieved_on' end,
    'period_start',null,'period_end',null,'quarter',null,'ingested_at',b.ingested_at,
    'coverage','Gangnam-gu','available',true,'unlocated_count',null,
    'limitations',case when kind.key='building_wfs' then jsonb_build_array('register_unlinked')
      else '[]'::jsonb end) from public.buildings b where b.source=kind.source limit 1)
  from (values ('building_shp','gis_buildings_shp'),('building_wfs','vworld_wfs_supplement')) kind(key,source)
  union all
  select 'building_registers', (select jsonb_build_object('source',source,
    'source_version',source_version,'reference_date',source_version,'date_kind','retrieved_on',
    'period_start',null,'period_end',null,'quarter',null,'ingested_at',ingested_at,
    'coverage','Gangnam-gu','available',true,'unlocated_count',null,'limitations','[]'::jsonb)
    from public.building_registers limit 1)
  union all
  select 'building_floors', (select jsonb_build_object('source',source,
    'source_version',source_version,'reference_date',source_version,'date_kind','retrieved_on',
    'period_start',null,'period_end',null,'quarter',null,'ingested_at',ingested_at,
    'coverage','Gangnam-gu','available',true,'unlocated_count',null,'limitations','[]'::jsonb)
    from public.building_floors limit 1)
  union all
  select 'legal_boundaries', (select jsonb_build_object('source',source,
    'source_version',source_version,'reference_date',source_version,'date_kind','retrieved_on',
    'period_start',null,'period_end',null,'quarter',null,'ingested_at',ingested_at,
    'coverage','Gangnam-gu','available',true,'unlocated_count',null,'limitations','[]'::jsonb)
    from public.legal_dongs limit 1)
  union all
  select 'commercial_trades', (select jsonb_build_object('source',source,
    'source_version',source_version,'reference_date',null,'date_kind','contract_period',
    'period_start',period_start,'period_end',period_end,'quarter',null,'ingested_at',ingested_at,
    'coverage','Gangnam-gu','available',true,'unlocated_count',null,
    'limitations',jsonb_build_array('legal_dong_not_radius','late_reports_and_cancellations_possible'))
    from public.commercial_trade_stats order by period_end desc limit 1)
  union all
  select 'rent_survey', (select jsonb_build_object('source',source,
    'source_version',source_version,'reference_date',null,'date_kind','quarter',
    'period_start',null,'period_end',null,'quarter',quarter,'ingested_at',ingested_at,
    'coverage','Gangnam-linked survey areas','available',true,'unlocated_count',null,
    'limitations',case when exists(select 1 from public.rent_areas where mapping_verified)
      then '[]'::jsonb else jsonb_build_array('no_verified_spatial_mapping') end)
    from public.rent_survey order by quarter desc limit 1)
), keys as (
  select unnest(array['stores','academies','schools','resident_population','admin_boundaries',
    'population_grid','living_population','subway_positions','bus_positions','transit_counts',
    'building_shp','building_wfs','building_registers','building_floors','legal_boundaries',
    'commercial_trades','rent_survey']) key
)
select jsonb_object_agg(keys.key,coalesce(items.value,jsonb_build_object(
  'source',null,'source_version',null,'reference_date',null,'date_kind','unknown',
  'period_start',null,'period_end',null,'quarter',null,'ingested_at',null,'coverage',null,
  'available',false,'unlocated_count',null,'limitations',jsonb_build_array('not_loaded'))))
from keys left join items using(key)
$$;

create function score_internal.demand(p extensions.geometry, circle extensions.geometry,
  radius_m integer, sources jsonb) returns jsonb
language sql stable security invoker set search_path='' as $$
with dongs as materialized (
 select d.adm_cd, extensions.st_area(extensions.st_intersection(
   extensions.st_transform(d.geom,5186),circle)) /
   nullif(extensions.st_area(extensions.st_transform(d.geom,5186)),0) weight
 from public.admin_dongs d
 where d.geom operator(extensions.&&) extensions.st_transform(circle,4326)
   and extensions.st_intersects(d.geom,extensions.st_transform(circle,4326))
), bands as (
 select b.age_band,case when count(d.adm_cd)>0 and count(a.population)=count(d.adm_cd)
   then sum(a.population*d.weight) end value
 from (values ('5_9'),('10_14'),('15_18')) b(age_band)
 left join dongs d on d.weight>0
 left join public.population_age a on a.adm_cd=d.adm_cd and a.age_band=b.age_band
 group by b.age_band
), population as (
 select jsonb_object_agg('pop_'||age_band,value) data from bands
), schools as (
 select jsonb_build_object('elem',count(*) filter(where level='elem'),
   'mid',count(*) filter(where level='mid'),'high',count(*) filter(where level='high')) data
 from public.schools where extensions.st_dwithin(geom::extensions.geography,p::extensions.geography,radius_m)
)
select population.data || jsonb_build_object('schools',case when
  (sources->'schools'->>'available')::boolean and exists(select 1 from dongs where weight>0)
  then schools.data else jsonb_build_object('elem',null,'mid',null,'high',null) end,'estimated',true)
from population cross join schools
$$;

create function score_internal.flow(circle extensions.geometry) returns jsonb
language sql stable security invoker set search_path='' as $$
with cells as materialized (
 select c.resolution_m,c.cell_id,
   extensions.st_area(extensions.st_intersection(extensions.st_transform(c.geom,5186),circle)) /
   nullif(extensions.st_area(extensions.st_transform(c.geom,5186)),0) weight
 from public.population_cells c
 where c.resolution_m=250 and c.geom operator(extensions.&&) extensions.st_transform(circle,4326)
   and extensions.st_intersects(c.geom,extensions.st_transform(circle,4326))
), hours as (
 select d.dow_type,h.hour,case when count(c.cell_id)>0 and count(l.total)=count(c.cell_id)
   then sum(l.total*c.weight) end value
 from (values ('weekday'),('weekend')) d(dow_type) cross join generate_series(0,23) h(hour)
 left join cells c on c.weight>0
 left join public.living_pop l on l.resolution_m=c.resolution_m and l.cell_id=c.cell_id
   and l.dow_type=d.dow_type and l.hour=h.hour
 group by d.dow_type,h.hour
), days as (
 select dow_type,jsonb_build_object('hourly',jsonb_agg(value order by hour),
   'golden_avg_pop',case when count(value) filter(where hour>=15 and hour<22)=7
    then avg(value) filter(where hour>=15 and hour<22) end) data from hours group by dow_type
)
select jsonb_object_agg(dow_type,data)||jsonb_build_object('estimated',true) from days
$$;

create function score_internal.transit(p extensions.geometry,radius_m integer,sources jsonb,
  covered boolean) returns jsonb language sql stable security invoker set search_path='' as $$
with nearby as materialized (
 select id,type from public.transit_stops
 where extensions.st_dwithin(geom::extensions.geography,p::extensions.geography,radius_m)
), stations as (
 select n.id,count(b.hour) hours,count(b.boarding) boarding_hours,count(b.alighting) alighting_hours,
   sum(b.boarding+b.alighting) observed from nearby n left join public.transit_boardings b
   on b.stop_id=n.id and b.hour>=15 and b.hour<22 where n.type='subway' group by n.id
), totals as (
 select case when count(*) filter(where hours<>7 or boarding_hours<>7 or alighting_hours<>7)=0
   then coalesce(sum(observed),0) end golden,
   count(*) filter(where hours<>7 or boarding_hours<>7 or alighting_hours<>7) missing from stations
), bus as (select count(*) n from nearby where type='bus'), nearest as (
 select min(extensions.st_distance(geom::extensions.geography,p::extensions.geography)) distance
 from public.transit_stops where type='subway' and
   extensions.st_dwithin(geom::extensions.geography,p::extensions.geography,2000)
)
select jsonb_build_object('nearest_subway_m',case when covered and
 (sources->'subway_positions'->>'available')::boolean then nearest.distance end,
 'bus_stops',case when covered and (sources->'bus_positions'->>'available')::boolean then bus.n end,
 'subway_boardings_golden',case when covered and (sources->'transit_counts'->>'available')::boolean
   and (sources->'subway_positions'->>'available')::boolean then totals.golden end,
 'subway_units_missing_golden',totals.missing,'estimated',false)
from totals cross join bus cross join nearest
$$;

create function score_internal.market(p extensions.geometry,radius_m integer,available boolean)
returns jsonb language sql stable security invoker set search_path='' as $$
with groups as (
 select inds_lcls,count(*) n from public.stores where
   extensions.st_dwithin(geom::extensions.geography,p::extensions.geography,radius_m)
 group by inds_lcls
)
select jsonb_build_object('stores_total',case when available then coalesce(sum(n),0) end,
 'stores_by_lcls',case when available then coalesce(jsonb_object_agg(inds_lcls,n),'{}'::jsonb) end,
 'estimated',false) from groups
$$;

create function score_internal.compete(p extensions.geometry,radius_m integer,available boolean)
returns jsonb language sql stable security invoker set search_path='' as $$
with groups as (
 select field,count(*) n from public.academies where registration_status='개원' and
   extensions.st_dwithin(geom::extensions.geography,p::extensions.geography,radius_m)
 group by field
)
select jsonb_build_object('academies_total',case when available then coalesce(sum(n),0) end,
 'academies_by_field',case when available then coalesce(jsonb_object_agg(field,n),'{}'::jsonb) end,
 'estimated',false) from groups
$$;

create function score_internal.building(p extensions.geometry,radius_m integer,requested_floor integer)
returns jsonb language sql stable security invoker set search_path='' as $$
with nearby as materialized (
 select b.* from public.buildings b where
  extensions.st_dwithin(b.geom::extensions.geography,p::extensions.geography,radius_m)
), containing as materialized (
 select * from nearby where extensions.st_covers(geom,p)
), selected as (
 select * from containing where (select count(*) from containing)=1
), candidate as (
 select jsonb_build_object('id',b.id,'source',b.source,'register_pk',b.register_pk,
   'floors_above',b.floors_above,'height_m',b.height_m,'height_estimated',b.height_estimated,
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
 select count(*) total,count(*) filter(where height_source='unknown') unknown from nearby
)
select jsonb_build_object('data',coalesce((select data from candidate),jsonb_build_object(
 'id',null,'source',null,'register_pk',null,'floors_above',null,'height_m',null,
 'height_estimated',null,'height_source',null,'floor_use',null,
 'elevators',jsonb_build_object('passenger',null,'emergency',null),'estimated',false)),
 'height_quality',jsonb_build_object('radius_m',radius_m,'total_buildings',total,
   'unknown_buildings',unknown,'unknown_ratio',unknown::numeric/nullif(total,0)),
 'reason',case (select count(*) from containing) when 0 then 'no_containing_building'
  when 1 then 'source_or_requested_floor_missing' else 'ambiguous_containing_building' end)
from quality
$$;

-- Enumerate actual null leaves, including array positions, for a machine-readable contract.
create function score_internal.null_paths(payload jsonb) returns table(path text)
language sql immutable security invoker set search_path='' as $$
with recursive walk(path,value) as (
 select key,value from jsonb_each(payload)
 union all
 select w.path || case when jsonb_typeof(w.value)='array' then '['||child.key||']'
   else '.'||child.key end,child.value
 from walk w cross join lateral (
  select key,value from jsonb_each(case when jsonb_typeof(w.value)='object' then w.value else '{}'::jsonb end)
  union all
  select (ordinality-1)::text,value from jsonb_array_elements(
   case when jsonb_typeof(w.value)='array' then w.value else '[]'::jsonb end) with ordinality
 ) child
)
select path from walk where value='null'::jsonb order by path
$$;

create function public.score_inputs(lat double precision,lng double precision,radius_m integer,floor integer)
returns jsonb language plpgsql stable security invoker set search_path='' as $$
declare
 p extensions.geometry; circle extensions.geometry; sources jsonb; covered boolean;
 result jsonb='{}'; timings jsonb='{}'; reasons jsonb='{}'; value jsonb; b jsonb; rent jsonb;
 started timestamptz; total_started timestamptz=clock_timestamp(); missing jsonb; estimated jsonb='[]';
begin
 if lat is null or lng is null or radius_m is null or floor is null or
   not (lat between 33 and 39 and lng between 124 and 132 and radius_m between 1 and 5000)
   or floor=0 or floor not between -100 and 200 then
  raise exception 'Invalid score coordinates, radius or floor' using errcode='22023';
 end if;
 p:=extensions.st_setsrid(extensions.st_makepoint(lng,lat),4326);
 circle:=extensions.st_buffer(extensions.st_transform(p,5186),radius_m,32);
 started:=clock_timestamp(); sources:=score_internal.sources();
 covered:=exists(select 1 from public.admin_dongs d where extensions.st_covers(d.geom,p));
 timings:=timings||jsonb_build_object('sources',extract(epoch from clock_timestamp()-started)*1000);

 started:=clock_timestamp(); value:=score_internal.demand(p,circle,radius_m,sources);
 result:=result||jsonb_build_object('demand',value);
 timings:=timings||jsonb_build_object('demand',extract(epoch from clock_timestamp()-started)*1000);
 started:=clock_timestamp(); value:=score_internal.flow(circle);
 result:=result||jsonb_build_object('flow',value);
 timings:=timings||jsonb_build_object('flow',extract(epoch from clock_timestamp()-started)*1000);
 started:=clock_timestamp(); value:=score_internal.transit(p,radius_m,sources,covered);
 result:=result||jsonb_build_object('transit',value);
 timings:=timings||jsonb_build_object('transit',extract(epoch from clock_timestamp()-started)*1000);
 started:=clock_timestamp(); value:=score_internal.market(p,radius_m,covered and (sources->'stores'->>'available')::boolean);
 result:=result||jsonb_build_object('market',value);
 timings:=timings||jsonb_build_object('market',extract(epoch from clock_timestamp()-started)*1000);
 started:=clock_timestamp(); value:=score_internal.compete(p,radius_m,covered and (sources->'academies'->>'available')::boolean);
 result:=result||jsonb_build_object('compete',value);
 timings:=timings||jsonb_build_object('compete',extract(epoch from clock_timestamp()-started)*1000);
 started:=clock_timestamp(); b:=score_internal.building(p,radius_m,floor);
 result:=result||jsonb_build_object('building',b->'data');
 timings:=timings||jsonb_build_object('building',extract(epoch from clock_timestamp()-started)*1000);
 started:=clock_timestamp(); rent:=score_internal.rent_inputs(lng,lat,radius_m,floor,null);
 select jsonb_build_object(
  'trade_median_per_m2',rent->'trade_median_per_m2','trade_building_type',rent->'trade_building_type',
  'trade_sample_count',rent->'trade_sample_count','survey_rent_per_m2',rent->'survey_rent_per_m2',
  'survey_vacancy',rent->'survey_vacancy','rent_level',rent->'rent_level',
  'survey_building_class',rent->'survey_building_class','estimated',false,
  'trade_by_building_type',coalesce((select jsonb_agg(jsonb_build_object(
    'building_type',v->'trade_kind','sample_count',v->'sample_count',
    'median_per_m2',case when (v->>'sample_count')::int>=5 then v->'median_price_per_m2' else 'null'::jsonb end,
    'area_basis',v->'area_basis','period_start',v->'period_start','period_end',v->'period_end')
    order by v->>'trade_kind') from jsonb_array_elements(rent->'trade_by_building_type') v),'[]'::jsonb),
  'survey_by_building_class',coalesce((select jsonb_object_agg(key,jsonb_build_object(
    'rent_per_m2',v->'survey_rent_per_m2','vacancy_rate',v->'survey_vacancy',
    'rent_level',v->'rent_level','area_code',v->'area_code','quarter',v->'quarter'))
    from jsonb_each(rent->'survey_by_building_class') x(key,v)),'{}'::jsonb)) into value;
 result:=result||jsonb_build_object('rent',value);
 timings:=timings||jsonb_build_object('rent',extract(epoch from clock_timestamp()-started)*1000);

 reasons:=jsonb_build_object('demand','missing_population_or_school_coverage',
  'flow','missing_cell_or_hour','transit','missing_source_or_station_hours_or_outside_coverage',
  'market','not_loaded_or_outside_coverage','compete','not_loaded_or_outside_coverage',
  'building',b->'reason','rent',rent->'meta');
 select coalesce(jsonb_agg(jsonb_build_object('path',path,'reason',case
   when path like 'rent.trade%' then coalesce(rent->'meta'->>'trade_missing_reason','fewer_than_five_samples')
   when path like 'rent.%' then coalesce(rent->'meta'->>'survey_missing_reason','source_value_missing')
   else reasons->>split_part(path,'.',1) end) order by path),'[]'::jsonb)
 into missing from score_internal.null_paths(result);
 select coalesce(jsonb_agg(jsonb_build_object('path',path,'method','area_proportion_epsg5186') order by path),'[]'::jsonb)
 into estimated from (
  select 'demand.'||j.key path from jsonb_each(result->'demand') j where j.key like 'pop_%' and j.value<>'null'::jsonb
  union all
  select 'flow.'||day.key||'.hourly['||(h.ordinality-1)||']'
  from jsonb_each(result->'flow') day cross join lateral jsonb_array_elements(
   case when day.key in ('weekday','weekend') then day.value->'hourly' else '[]'::jsonb end)
   with ordinality h(value,ordinality) where h.value<>'null'::jsonb
  union all select 'flow.'||j.key||'.golden_avg_pop' from jsonb_each(result->'flow') j
   where j.key in ('weekday','weekend') and j.value->'golden_avg_pop'<>'null'::jsonb
 ) fields;
 if (result->'building'->>'height_estimated')::boolean then
  estimated:=estimated||jsonb_build_array(jsonb_build_object('path','building.height_m','method','approved_floor_height'));
 end if;
 return result||jsonb_build_object('meta',jsonb_build_object('schema_version','1.0',
  'radius_m',radius_m,'floor',floor,'computed_at',statement_timestamp(),'sources',sources,
  'estimated_fields',estimated,'missing_fields',missing,'height_quality',b->'height_quality',
  'legal_dong_code',rent->'meta'->'legal_dong_code','rent_spatial_scope','legal_dong_and_survey_area',
  'bundle_ms',timings-'sources','sources_ms',timings->'sources',
  'total_ms',extract(epoch from clock_timestamp()-total_started)*1000));
end;
$$;

revoke all on all functions in schema score_internal from public;
grant execute on all functions in schema score_internal to anon,authenticated;
revoke all on function public.score_inputs(double precision,double precision,integer,integer) from public;
grant execute on function public.score_inputs(double precision,double precision,integer,integer) to anon,authenticated;
