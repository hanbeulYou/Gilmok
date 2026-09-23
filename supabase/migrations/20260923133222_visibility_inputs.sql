-- Additive metric scene. Existing buildings_in_radius / score_inputs stay unchanged.
create function public.visibility_inputs(lng double precision, lat double precision)
returns jsonb language plpgsql stable security invoker set search_path = '' as $$
declare
  base jsonb;
  p extensions.geometry;
  projected extensions.geometry;
  sources jsonb;
  result jsonb;
begin
  -- Reuse both validation and the exact SHP/WFS selection/height contract.
  base := public.buildings_in_radius(lng, lat, 1000);
  p := extensions.st_setsrid(extensions.st_makepoint(lng,lat),4326);
  projected := extensions.st_transform(p,5186);
  sources := score_internal.sources();
  with shapes as materialized (
    select b.id, b.geom, extensions.st_transform(b.geom,5186) metric,
      f->'properties' props
    from jsonb_array_elements(base->'features') f
    join public.buildings b on b.id=f->>'id'
  ), containing as materialized (
    select id from shapes where extensions.st_covers(geom,p)
  ), station as materialized (
    select s.id,s.name,s.line,extensions.st_transform(s.geom,5186) metric,
      extensions.st_distance(s.geom::extensions.geography,p::extensions.geography) distance_m
    from public.transit_stops s where s.type='subway'
      and extensions.st_dwithin(s.geom::extensions.geography,p::extensions.geography,2000)
    order by distance_m,s.id limit 1
  ), schools as materialized (
    select s.id,s.name,s.level,extensions.st_transform(s.geom,5186) metric,
      extensions.st_distance(s.geom::extensions.geography,p::extensions.geography) distance_m
    from public.schools s where s.geom is not null
      and extensions.st_dwithin(s.geom::extensions.geography,p::extensions.geography,1000)
  ) select jsonb_build_object(
    'schema_version','0.1','srid',5186,'units','m','radius_m',1000,
    'candidate',jsonb_build_array(extensions.st_x(projected),extensions.st_y(projected)),
    'candidate_wgs84',jsonb_build_object('lat',lat,'lng',lng),
    'candidate_building_id',(select min(id) from containing having count(*)=1),
    'containing_building_count',(select count(*) from containing),
    'buildings',coalesce((select jsonb_agg(jsonb_build_object(
      'id',id,'polygons',case extensions.st_geometrytype(metric)
        when 'ST_Polygon' then jsonb_build_array(extensions.st_asgeojson(metric,15,0)::jsonb->'coordinates')
        else extensions.st_asgeojson(metric,15,0)::jsonb->'coordinates' end,
      'height_m',(props->'occlusion_height_m'),'height_source',props->'height_source',
      'estimated',props->'estimated','source',props->'source','source_version',props->'source_version'
    ) order by id) from shapes),'[]'::jsonb),
    'station',(select jsonb_build_object('id',id,'name',name,'line',line,'distance_m',distance_m,
      'point',jsonb_build_array(extensions.st_x(metric),extensions.st_y(metric))) from station),
    'schools',coalesce((select jsonb_agg(jsonb_build_object(
      'id',id,'name',name,'level',level,'distance_m',distance_m,
      'point',jsonb_build_array(extensions.st_x(metric),extensions.st_y(metric))) order by id)
      from schools),'[]'::jsonb),
    'sources',jsonb_build_object('building_shp',sources->'building_shp',
      'building_wfs',sources->'building_wfs','subway_positions',sources->'subway_positions',
      'schools',sources->'schools'),
    'coverage',jsonb_build_object('building_region','Gangnam-gu',
      'query_within_loaded_region',coalesce((select extensions.st_covers(
        extensions.st_unaryunion(extensions.st_collect(d.geom)),
        extensions.st_transform(extensions.st_buffer(projected,1000),4326))
        from public.admin_dongs d where left(d.adm_cd,5)='11680'),false)),
    'building_meta',base->'meta'
  ) into result;
  return result;
end;
$$;
revoke all on function public.visibility_inputs(double precision,double precision) from public;
grant execute on function public.visibility_inputs(double precision,double precision) to anon,authenticated;
