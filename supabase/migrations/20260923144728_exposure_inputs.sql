-- Add a versioned all-stations scene; leave visibility_inputs v0.1 intact.
create function public.exposure_inputs(lng double precision, lat double precision)
returns jsonb language plpgsql stable security invoker set search_path = '' as $$
declare
  base jsonb;
  p extensions.geometry;
  stations jsonb;
begin
  base := public.visibility_inputs(lng,lat);
  p := extensions.st_setsrid(extensions.st_makepoint(lng,lat),4326);
  select coalesce(jsonb_agg(jsonb_build_object(
    'id',s.id,'name',s.name,'line',s.line,'distance_m',s.distance_m,
    'point',jsonb_build_array(extensions.st_x(s.metric),extensions.st_y(s.metric)))
    order by s.distance_m,s.id),'[]'::jsonb) into stations
  from (
    select id,name,line,extensions.st_transform(geom,5186) metric,
      extensions.st_distance(geom::extensions.geography,p::extensions.geography) distance_m
    from public.transit_stops where type='subway'
      and extensions.st_dwithin(geom::extensions.geography,p::extensions.geography,1000)
  ) s;
  return (base-'station') || jsonb_build_object('schema_version','0.2','stations',stations);
end;
$$;
revoke all on function public.exposure_inputs(double precision,double precision) from public;
grant execute on function public.exposure_inputs(double precision,double precision) to anon,authenticated;
