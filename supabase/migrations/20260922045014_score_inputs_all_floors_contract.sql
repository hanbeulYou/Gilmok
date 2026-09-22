-- Additive v1.2 contract: preserve requested floor_use and return all register floor rows.
-- No table or stored cache changes. Rollback by a new migration restoring these definitions.
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
      'all_floors',coalesce(f.all_floors,'[]'::jsonb),
   'elevators',jsonb_build_object('passenger',r.passenger_elevators,'emergency',r.emergency_elevators),
   'estimated',b.height_estimated) data
 from selected b left join public.building_registers r on r.register_pk=b.register_pk
 left join lateral (
  select jsonb_agg(jsonb_build_object('use_code',use_code,'use_name',use_name,'other_use',other_use,
   'area_m2',area,'main_attached_code',main_attached_code) order by id)
    filter(where floor_kind=case when requested_floor>0 then '20' else '10' end
      and floor_no=abs(requested_floor)) uses,
    jsonb_agg(jsonb_build_object(
      'floor_no',case when floor_kind='10' then -abs(floor_no) else floor_no end,
      'floor_kind',floor_kind,'use_name',use_name,'area_m2',area)
      order by case when floor_kind='10' then -abs(floor_no) else floor_no end,
      floor_kind,use_name,area,id) all_floors
  from public.building_floors where register_pk=b.register_pk
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
 'id',null,'all_floors','[]'::jsonb,'source',null,'register_pk',null,'floors_above',null,'floors_below',null,'pnu',null,'location_basis',null,
 'main_use',jsonb_build_object('code',null,'name',null,'other_use',null),'height_m',null,
 'height_estimated',null,'height_source',null,'floor_use',null,
 'elevators',jsonb_build_object('passenger',null,'emergency',null),'estimated',false)),
 'height_quality',jsonb_build_object('radius_m',radius_m,'total_buildings',total,
   'unknown_buildings',unknown,'observed_buildings',observed_total,'observed_unknown_buildings',observed_unknown,
 'excluded_buildings',excluded,'excluded_unknown_buildings',excluded_unknown,'excluded_small_buildings',excluded_small,'excluded_use_buildings',excluded_use,'unknown_ratio',unknown::numeric/nullif(total,0)),
 'reason',case (select count(*) from containing) when 0 then 'no_containing_building'
  when 1 then 'source_or_requested_floor_missing' else 'ambiguous_containing_building' end)
from quality
$function$
;
CREATE OR REPLACE FUNCTION score_internal.address_building(address text, requested_floor integer, p extensions.geometry)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
AS $function$
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
   data:=(c.payload->'building')||jsonb_build_object('floor_use',uses,
        'all_floors',coalesce((select jsonb_agg(jsonb_build_object(
          'floor_no',case when f->>'floor_kind'='10' then -abs((f->>'floor_no')::integer)
            else (f->>'floor_no')::integer end,
          'floor_kind',f->'floor_kind','use_name',f->'use_name','area_m2',f->'area_m2')
          order by case when f->>'floor_kind'='10' then -abs((f->>'floor_no')::integer)
            else (f->>'floor_no')::integer end,
          f->>'floor_kind',f->>'use_name',(f->>'area_m2')::numeric)
          from jsonb_array_elements(c.payload->'floors') f),'[]'::jsonb));
  end if;
  return jsonb_build_object('status',c.status,'address',normalized,'data',data,
   'pnu',c.pnu,'fetched_at',c.fetched_at,'expires_at',c.expires_at,
   'address_distance_m',extensions.st_distance(c.geom::extensions.geography,p::extensions.geography));
 end if;
 insert into ingest_private.building_address_requests(address) values(normalized)
 on conflict on constraint building_address_requests_pkey do update set status='pending',requested_at=clock_timestamp(),
   started_at=null,finished_at=null,error_code=null
 where building_address_requests.status='done';
 select x.status into state from ingest_private.building_address_requests x where x.address=normalized;
 return jsonb_build_object('status',state,'address',normalized);
end;
$function$
;
CREATE OR REPLACE FUNCTION public.score_inputs(lat double precision, lng double precision, radius_m integer, floor integer, address text DEFAULT NULL::text)
 RETURNS jsonb
 LANGUAGE plpgsql
 SET search_path TO ''
AS $function$
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
   when b->>'id' is null then coalesce((select item->>'reason' from jsonb_array_elements(r->'meta'->'missing_fields') item where item->>'path'='building.id' limit 1),'no_containing_building')
   else 'source_or_requested_floor_missing' end)
  from score_internal.null_paths(jsonb_build_object('building',b))
 ) entries;
 select coalesce(jsonb_agg(item order by item->>'path'),'[]'::jsonb) into estimated
 from jsonb_array_elements(r->'meta'->'estimated_fields') item
 where item->>'path' not like 'building.%' or coalesce((b->>'height_estimated')::boolean,false);
 r:=jsonb_set(r,'{meta,missing_fields}',missing);
 r:=jsonb_set(r,'{meta,estimated_fields}',estimated);
 r:=jsonb_set(r,'{meta,schema_version}','"1.2"');
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
$function$
;
