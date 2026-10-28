-- Add a separate Juso coordinate counter; retain legacy counts and RPC contract.
alter table app_private.address_daily_usage
  add column juso_coordinate integer not null default 0 check (juso_coordinate >= 0);

create or replace function public.claim_address_call(provider text) returns boolean
language plpgsql security definer set search_path='' as $$
declare accepted integer;
begin
  if auth.uid() is null then
    raise exception 'authentication_required' using errcode='42501';
  end if;
  if provider is null or provider not in ('juso_search','juso_coordinate','vworld_coordinate') then
    raise exception 'invalid_address_provider' using errcode='22023';
  end if;
  insert into app_private.address_daily_usage as u
    (user_id,day_kst,total,juso_search,juso_coordinate,vworld_coordinate)
  values(auth.uid(),(now() at time zone 'Asia/Seoul')::date,1,
    (provider='juso_search')::integer,(provider='juso_coordinate')::integer,
    (provider='vworld_coordinate')::integer)
  on conflict(user_id,day_kst) do update set total=u.total+1,
    juso_search=u.juso_search+excluded.juso_search,
    juso_coordinate=u.juso_coordinate+excluded.juso_coordinate,
    vworld_coordinate=u.vworld_coordinate+excluded.vworld_coordinate
  where u.total<100 returning total into accepted;
  if accepted is not null then perform public.touch_user_activity(); end if;
  return accepted is not null;
end;
$$;
revoke all on function public.claim_address_call(text) from public,anon;
grant execute on function public.claim_address_call(text) to authenticated;

-- Coordinate conversion only: no provider IO and no table/cache/queue writes.
create function public.project_juso_coordinate(source_x double precision,source_y double precision)
returns jsonb language plpgsql stable security invoker set search_path='' as $$
declare point extensions.geometry; lng double precision; lat double precision;
begin
  if source_x is null or source_y is null
    or not (source_x>0 and source_x<2000000 and source_y>0 and source_y<3000000) then
    raise exception 'invalid_juso_coordinate' using errcode='22023';
  end if;
  point:=extensions.st_transform(extensions.st_setsrid(
    extensions.st_makepoint(source_x,source_y),5179),4326);
  lng:=extensions.st_x(point); lat:=extensions.st_y(point);
  if not (lng between 124 and 132 and lat between 33 and 39) then
    raise exception 'invalid_juso_coordinate' using errcode='22023';
  end if;
  return jsonb_build_object('lng',lng,'lat',lat);
end;
$$;
revoke all on function public.project_juso_coordinate(double precision,double precision)
  from public,anon;
grant execute on function public.project_juso_coordinate(double precision,double precision)
  to authenticated;

-- Rollback: disable new registration first; keep candidates and usage history.
-- Restore the previous claim_address_call body only after the new app is stopped.
-- Do not automatically resume the Vworld writer or erase either provider counter.
