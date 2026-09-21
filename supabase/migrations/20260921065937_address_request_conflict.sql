-- Qualify conflict target; avoid collision with the optional address parameter.
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
   data:=(c.payload->'building')||jsonb_build_object('floor_use',uses);
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
$function$;
