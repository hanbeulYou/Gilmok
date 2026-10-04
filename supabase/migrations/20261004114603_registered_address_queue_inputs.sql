-- Preserve the five-argument scoring contract. Registration supplies its already
-- resolved public PNU/point atomically with any queue write through a six-argument overload.
alter table ingest_private.building_address_requests
 add column pnu text check(pnu ~ '^11680[0-9]{14}$'),
 add column geom extensions.geometry(Point,4326),
 add column coordinate_source text check(coordinate_source in ('registration','juso'));
alter table ingest_private.building_address_requests
 drop constraint building_address_requests_status_check,
 add constraint building_address_requests_status_check
 check(status in ('pending','processing','done','failed','needs_coord'));
alter table ingest_private.geocode_requests drop constraint geocode_requests_status_check,
 add constraint geocode_requests_status_check check(status in
 ('pending','success','not_found','ambiguous','invalid','blocked','unknown','needs_coord'));

create function ingest_private.bind_registered_location() returns trigger
language plpgsql security definer set search_path='' as $$
declare input jsonb:=nullif(current_setting('gilmok.registered_location',true),'')::jsonb;
begin
 if new.status='pending' and input->>'address'=new.address then
   new.pnu:=input->>'pnu';
   new.geom:=extensions.st_setsrid(extensions.st_makepoint(
     (input->>'lng')::float8,(input->>'lat')::float8),4326);
   new.coordinate_source:='registration';
 end if;
 return new;
end $$;
revoke all on function ingest_private.bind_registered_location() from public,anon,authenticated,service_role;
-- Strict input binding, not ancillary projection: invalid inputs must roll back.
create trigger a_bind_registered_location before insert or update
 on ingest_private.building_address_requests for each row
 execute function ingest_private.bind_registered_location();

create function public.score_inputs(lat double precision,lng double precision,radius_m integer,
 floor integer,address text,registered_pnu text) returns jsonb
language plpgsql security invoker set search_path='' set extra_float_digits='3' as $$
declare prior text:=current_setting('gilmok.registered_location',true); result jsonb;
begin
 if auth.uid() is null then raise exception 'authentication_required' using errcode='42501'; end if;
 if registered_pnu is null or registered_pnu !~ '^11680[0-9]{14}$'
   or lat is null or lng is null or lat not between 33 and 39 or lng not between 124 and 132
   or score_internal.normalize_building_address(address) is null then
   raise exception 'invalid_registered_location' using errcode='22023';
 end if;
 perform set_config('gilmok.registered_location',jsonb_build_object(
   'address',score_internal.normalize_building_address(address),'pnu',registered_pnu,
   'lat',lat,'lng',lng)::text,true);
 perform score_internal.resume_registered_location();
 result:=public.score_inputs(lat,lng,radius_m,floor,address);
 perform set_config('gilmok.registered_location',coalesce(prior,''),true);
 return result;
end $$;
revoke all on function public.score_inputs(double precision,double precision,integer,integer,text,text)
 from public,anon,service_role;
grant execute on function public.score_inputs(double precision,double precision,integer,integer,text,text)
 to authenticated;

create function score_internal.resume_registered_location() returns void
language plpgsql security definer set search_path='' as $$
declare input jsonb:=nullif(current_setting('gilmok.registered_location',true),'')::jsonb;
begin
 if auth.uid() is null or input is null then
   raise exception 'authentication_required' using errcode='42501';
 end if;
 update ingest_private.building_address_requests set status='pending',
   requested_at=clock_timestamp(),started_at=null,finished_at=null,error_code=null
 where address=input->>'address' and (status='needs_coord' or
   (status in ('failed','pending','processing') and (pnu is null or geom is null)));
end $$;
revoke all on function score_internal.resume_registered_location() from public,anon,service_role;
grant execute on function score_internal.resume_registered_location() to authenticated;
-- The private function grants no table access; input context is set only by the authenticated RPC.

create or replace function app_private.current_lookup_status(requested_address text)
returns text language sql stable security definer set search_path='' as $$
 select coalesce(
   (select c.status from ingest_private.building_address_cache c where c.address=requested_address and c.expires_at>now()),
   (select case r.status when 'done' then 'failed' when 'needs_coord' then 'pending' else r.status end
    from ingest_private.building_address_requests r where r.address=requested_address));
$$;
notify pgrst,'reload schema';

-- Operational hold stays pending in the public v1.3 contract; only the batch
-- status/report carries needs_coord. Registration can supply the missing input.
create or replace function public.score_inputs(lat double precision,lng double precision,
 radius_m integer,floor integer,address text default null) returns jsonb
language plpgsql security invoker set search_path='' set extra_float_digits='3' as $$
declare result jsonb; request_id uuid;
begin
 result:=score_internal.score_inputs_registration_base(lat,lng,radius_m,floor,address);
 if result->'meta'->'building_lookup'->>'status'='needs_coord' then
   result:=jsonb_set(result,'{meta,building_lookup,status}','"pending"'::jsonb);
 end if;
 if auth.uid() is not null and result->'meta'->'building_lookup'->>'status'
   in ('pending','processing','failed') then
   request_id:=public.watch_candidate_lookup(result->'meta'->'building_lookup'->>'address');
   result:=jsonb_set(result,'{meta,building_lookup,request_id}',coalesce(to_jsonb(request_id),'null'::jsonb));
 end if;
 return result;
end $$;
