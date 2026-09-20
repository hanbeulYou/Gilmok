with origin as (
  select extensions.st_setsrid(extensions.st_makepoint(%(lng)s,%(lat)s),4326)
         ::extensions.geography as geog
), nearby_stores as materialized (
  select inds_lcls from public.stores,origin
  where extensions.st_dwithin(geom::extensions.geography,geog,%(radius)s)
), nearby_academies as materialized (
  select field from public.academies,origin
  where geom is not null and registration_status='개원'
    and extensions.st_dwithin(geom::extensions.geography,geog,%(radius)s)
), nearby_schools as materialized (
  select level from public.schools,origin
  where geom is not null
    and extensions.st_dwithin(geom::extensions.geography,geog,%(radius)s)
)
select jsonb_build_object(
  'market',case when exists (select 1 from ingest_private.place_snapshots
                            where target_table='stores') then jsonb_build_object(
    'stores_total',(select count(*) from nearby_stores),
    'stores_by_lcls',coalesce((select jsonb_object_agg(inds_lcls,n)
      from (select inds_lcls,count(*) n from nearby_stores group by inds_lcls) a),'{}'::jsonb)) end,
  'compete',case when exists (select 1 from ingest_private.place_snapshots
                             where target_table='academies') then jsonb_build_object(
    'academies_total',(select count(*) from nearby_academies),
    'academies_by_field',coalesce((select jsonb_object_agg(field,n)
      from (select field,count(*) n from nearby_academies group by field) a),'{}'::jsonb)) end,
  'schools',case when exists (select 1 from ingest_private.place_snapshots
                             where target_table='schools') then jsonb_build_object(
    'elem',(select count(*) from nearby_schools where level='elem'),
    'mid',(select count(*) from nearby_schools where level='mid'),
    'high',(select count(*) from nearby_schools where level='high')) end,
  'meta',coalesce((select jsonb_object_agg(target_table,jsonb_build_object(
    'source',source,'source_version',source_version,'row_count',row_count,
    'located_count',located_count,'unlocated_count',row_count-located_count,
    'estimated',estimated,'counts_are_located_only',true))
    from ingest_private.place_snapshots),'{}'::jsonb)
);
