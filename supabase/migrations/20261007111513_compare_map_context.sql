-- Additive: one read-only RPC and its grants. No existing objects or rows changed.
create function public.compare_map_context(lat double precision, lng double precision)
returns jsonb language plpgsql stable security invoker set search_path='' set extra_float_digits='3' as $$
declare
  center extensions.geometry;
  covered boolean;
  features jsonb;
  sources jsonb;
begin
  if lat is null or lng is null or not(lat between 33 and 39 and lng between 124 and 132) then
    raise exception 'invalid_map_coordinate' using errcode='22023';
  end if;
  center:=extensions.st_setsrid(extensions.st_makepoint(lng,lat),4326);
  select exists(select 1 from public.admin_dongs d where left(d.adm_cd,2)='11'
    and extensions.st_covers(d.geom,center)) into covered;

  select jsonb_build_object(
    'transit_stops',(select jsonb_build_object('available',covered and count(*)>0,'coverage','Seoul',
      'source_versions',coalesce(jsonb_agg(distinct source_version),'[]'::jsonb),
      'sources',coalesce(jsonb_agg(distinct source),'[]'::jsonb),'latest_ingested_at',max(ingested_at),
      'unlocated_count',0) from public.transit_stops where type='subway'),
    'schools',(select jsonb_build_object('available',covered and count(*)>0,'coverage','Seoul',
      'source_versions',coalesce(jsonb_agg(distinct source_version),'[]'::jsonb),
      'sources',coalesce(jsonb_agg(distinct source),'[]'::jsonb),'latest_ingested_at',max(ingested_at),
      'unlocated_count',count(*) filter(where geom is null)) from public.schools)
  ) into sources;

  with rings as (
    select radius_m,extensions.st_makepolygon(extensions.st_addpoint(
      extensions.st_makeline(array(select extensions.st_project(center::extensions.geography,
        radius_m,2*pi()*i/128)::extensions.geometry from generate_series(0,127) i)),
      extensions.st_project(center::extensions.geography,radius_m,0)::extensions.geometry)) as geom
    from (values(800),(1000)) r(radius_m)
  ), items as (
    select 'radius:'||radius_m as id,geom,jsonb_build_object('kind','radius','radius_m',radius_m,
      'purpose',case when radius_m=800 then 'primary' else 'school' end) as properties from rings
    union all
    select 'station:'||s.id,s.geom,jsonb_build_object('kind','station','source_id',s.id,
      'name',s.name,'line',s.line,'estimated',s.estimated,'distance_m',extensions.st_distance(center::extensions.geography,s.geom::extensions.geography))
    from public.transit_stops s where covered and s.type='subway'
      and extensions.st_dwithin(s.geom::extensions.geography,center::extensions.geography,1200)
    union all
    select 'school:'||s.id,s.geom,jsonb_build_object('kind','school','source_id',s.id,
      'name',s.name,'level',s.level,'estimated',s.estimated,'distance_m',extensions.st_distance(center::extensions.geography,s.geom::extensions.geography))
    from public.schools s where covered and s.geom is not null
      and extensions.st_dwithin(s.geom::extensions.geography,center::extensions.geography,1000)
  ) select coalesce(jsonb_agg(jsonb_build_object('type','Feature','id',id,
      'geometry',extensions.st_asgeojson(geom,15)::jsonb,'properties',properties) order by id),'[]'::jsonb)
    into features from items;
  return jsonb_build_object('schema_version','1.0','center',jsonb_build_array(lng,lat),
    'collection',jsonb_build_object('type','FeatureCollection','features',features),
    'meta',jsonb_build_object('crs','EPSG:4326','covered',covered,'coverage','Seoul',
      'radius_m',jsonb_build_array(800,1000),'station_radius_m',1200,'school_radius_m',1000,
      'sources',sources,'unlocated_scope','whole_source_not_radius','computed_at',statement_timestamp()));
end;
$$;
revoke all on function public.compare_map_context(double precision,double precision) from public,anon;
grant execute on function public.compare_map_context(double precision,double precision) to authenticated;
notify pgrst,'reload schema';
