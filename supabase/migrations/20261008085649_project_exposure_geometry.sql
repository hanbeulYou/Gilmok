-- New read-only function and grants only; no existing objects or rows changed.
create function public.project_exposure_geometry(items jsonb)
returns jsonb language plpgsql immutable security invoker
set search_path='' set extra_float_digits='3'
as $$
declare
  valid boolean;
  vertices bigint;
  projected jsonb;
begin
  if items is null or jsonb_typeof(items) <> 'array' then
    raise exception 'Expected a geometry item array' using errcode='22023';
  end if;
  if octet_length(items::text) > 8388608 or jsonb_array_length(items) > 10000 then
    raise exception 'Geometry display limit exceeded (8MiB / 10000 items)' using errcode='22023';
  end if;
  if exists(select 1 from jsonb_array_elements(items) i where
      jsonb_typeof(i) <> 'object' or jsonb_typeof(i->'id') is distinct from 'string'
      or length(i->>'id') not between 1 and 200
      or jsonb_typeof(i->'geometry') is distinct from 'object'
      or coalesce(i->'geometry'->>'type','') not in ('Point','LineString','Polygon','MultiPolygon')
      or jsonb_typeof(i->'geometry'->'coordinates') is distinct from 'array')
    or (select count(distinct i->>'id') from jsonb_array_elements(items) i) <> jsonb_array_length(items) then
    raise exception 'Invalid or duplicate geometry item' using errcode='22023';
  end if;
  with parsed as materialized (
    select i->>'id' id, n, extensions.st_setsrid(extensions.st_geomfromgeojson(i->'geometry'),5186) geom
    from jsonb_array_elements(items) with ordinality as x(i,n)
  ), checked as (
    select coalesce(bool_and(not extensions.st_isempty(geom) and extensions.st_ndims(geom)=2
      and extensions.st_isvalid(geom)
      and extensions.st_xmin(geom) between -100000 and 700000
      and extensions.st_xmax(geom) between -100000 and 700000
      and extensions.st_ymin(geom) between 100000 and 1000000
      and extensions.st_ymax(geom) between 100000 and 1000000),true) ok,
      coalesce(sum(extensions.st_npoints(geom)),0) points from parsed
  )
  select ok, points, case when ok and points<=200000 then
    (select coalesce(jsonb_agg(jsonb_build_object('id',id,'geometry',
      extensions.st_asgeojson(extensions.st_transform(geom,4326),15,0)::jsonb) order by n),'[]'::jsonb)
      from parsed) else null end into valid, vertices, projected from checked;
  if not valid or vertices>200000 then
    raise exception 'Invalid geometry or display vertex limit exceeded (200000)' using errcode='22023';
  end if;
  return projected;
exception when others then
  if sqlstate='22023' then raise; end if;
  raise exception 'Invalid EPSG:5186 display geometry' using errcode='22023';
end;
$$;
revoke all on function public.project_exposure_geometry(jsonb) from public, anon;
grant execute on function public.project_exposure_geometry(jsonb) to authenticated;
comment on function public.project_exposure_geometry(jsonb) is
  'Display-only exact cached geometry projection from EPSG:5186 to EPSG:4326; no database geometry lookup or writes.';
