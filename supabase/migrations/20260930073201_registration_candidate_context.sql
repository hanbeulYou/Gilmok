-- Read-only candidate/context validation. No coordinate substitution or API response storage.
-- Rollback: revoke this new function; original data and scoring RPCs remain intact.
create function public.resolve_candidate_location(lat double precision,lng double precision,pnu text default null)
returns jsonb language plpgsql stable security invoker
set search_path='' set extra_float_digits='3' as $$
declare
  point_geom extensions.geometry;
  city extensions.geometry;
  legal_name text;
  legal_code text;
  candidates jsonb;
  n integer;
  matching integer;
  state text;
  inside boolean;
begin
  if lat is null or lng is null or not (lat between -90 and 90) or not (lng between -180 and 180)
    or (pnu is not null and pnu !~ '^[0-9]{19}$') then
    raise exception 'invalid_candidate_location' using errcode='22023';
  end if;
  point_geom := extensions.st_setsrid(extensions.st_makepoint(lng,lat),4326);
  select exists(select 1 from public.admin_dongs a where extensions.st_covers(a.geom,point_geom)) into inside;
  select extensions.st_unaryunion(extensions.st_collect(a.geom)) into city from public.admin_dongs a;
  select count(*),count(*) filter(where resolve_candidate_location.pnu is null or b.pnu=resolve_candidate_location.pnu),
    coalesce(jsonb_agg(jsonb_build_object('id',b.id,'pnu',b.pnu,'register_pk',b.register_pk) order by b.id),'[]'::jsonb)
    into n,matching,candidates from public.buildings b where extensions.st_covers(b.geom,point_geom);
  state := case when not inside then 'outside_seoul'
    when n=0 then 'footprint_missing' when n>1 then 'ambiguous_footprint'
    when matching=0 then 'pnu_mismatch' else 'matched' end;
  legal_code := left(coalesce(pnu,candidates->0->>'pnu'),8);
  select l.name into legal_name from public.legal_dongs l where l.code8=legal_code;
  return jsonb_build_object('lat',lat,'lng',lng,'pnu',pnu,'status',state,
    'building',case when state='matched' then candidates->0 else null end,
    'covering_building_count',n,
    'context',jsonb_build_object('inside_seoul',case when city is null then null else inside end,
      'seoul_boundary_distance_m',case when city is null then null else
        extensions.st_distance(extensions.st_collect(array(
          select extensions.st_exteriorring(part.geom) from extensions.st_dump(city) part
        ))::extensions.geography,point_geom::extensions.geography) end,
      'legal_dong_names',case when legal_name is null then '{}'::jsonb
        else jsonb_build_object(legal_code,legal_name) end));
end;
$$;
revoke all on function public.resolve_candidate_location(double precision,double precision,text) from public,anon;
grant execute on function public.resolve_candidate_location(double precision,double precision,text) to authenticated,service_role;
