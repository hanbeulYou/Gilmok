-- Distinguish missing cell values from missing geometry; preserve source version separately.
create or replace function score_internal.sources() returns jsonb
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
    'source_version',source_version,'reference_date',case when source_version ~ '^[0-9]{8}T[0-9]{6}Z$'
      then to_char(to_date(left(source_version,8),'YYYYMMDD'),'YYYY-MM-DD') end,
    'date_kind','retrieved_on','period_start',null,'period_end',null,'quarter',null,'ingested_at',ingested_at,
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

create or replace function score_internal.flow(circle extensions.geometry) returns jsonb
language sql stable security invoker set search_path='' as $$
with cells as materialized (
 select c.resolution_m,c.cell_id,
   extensions.st_area(extensions.st_intersection(extensions.st_transform(c.geom,5186),circle)) /
   nullif(extensions.st_area(extensions.st_transform(c.geom,5186)),0) weight
 from public.population_cells c
 where c.resolution_m=250 and c.geom operator(extensions.&&) extensions.st_transform(circle,4326)
   and extensions.st_intersects(c.geom,extensions.st_transform(circle,4326))
), hours as (
 select d.dow_type,h.hour,count(c.cell_id) expected_cells,count(l.total) valid_cells,case when count(c.cell_id)>0 and count(l.total)=count(c.cell_id)
   then sum(l.total*c.weight) end value
 from (values ('weekday'),('weekend')) d(dow_type) cross join generate_series(0,23) h(hour)
 left join cells c on c.weight>0
 left join public.living_pop l on l.resolution_m=c.resolution_m and l.cell_id=c.cell_id
   and l.dow_type=d.dow_type and l.hour=h.hour
 group by d.dow_type,h.hour
), days as (
 select dow_type,jsonb_build_object('hourly',jsonb_agg(value order by hour),
   'golden_avg_pop',case when count(value) filter(where hour>=15 and hour<22)=7
    then avg(value) filter(where hour>=15 and hour<22) end) data,
   jsonb_build_object('expected_cells',max(expected_cells),'valid_cells',jsonb_agg(valid_cells order by hour)) coverage from hours group by dow_type
)
select jsonb_object_agg(dow_type,data)||jsonb_build_object('estimated',true,'_coverage',jsonb_object_agg(dow_type,coverage)) from days
$$;

create or replace function public.score_inputs(lat double precision,lng double precision,radius_m integer,floor integer)
returns jsonb language plpgsql stable security invoker set search_path='' as $$
declare
 p extensions.geometry; circle extensions.geometry; sources jsonb; covered boolean;
 result jsonb='{}'; timings jsonb='{}'; reasons jsonb='{}'; value jsonb; b jsonb; rent jsonb;
 started timestamptz; total_started timestamptz=clock_timestamp(); missing jsonb; flow_coverage jsonb; estimated jsonb='[]';
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
 flow_coverage:=value->'_coverage';
 result:=result||jsonb_build_object('flow',value-'_coverage');
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
  'estimated_fields',estimated,'missing_fields',missing,'flow_coverage',flow_coverage,'height_quality',b->'height_quality',
  'legal_dong_code',rent->'meta'->'legal_dong_code','rent_spatial_scope','legal_dong_and_survey_area',
  'bundle_ms',timings-'sources','sources_ms',timings->'sources',
  'total_ms',extract(epoch from clock_timestamp()-total_started)*1000));
end;
$$;

