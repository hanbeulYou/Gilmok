-- Retain no-match versus ambiguity diagnostics when address fallback is unused.
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
$function$;
