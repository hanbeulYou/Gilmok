-- Preserve v0.2.1 for replay; score coverage differs from the full approach query coverage.
create function public.exposure_inputs_v022(lng double precision, lat double precision)
returns jsonb language plpgsql stable security invoker set search_path = '' as $$
declare
  base jsonb;
  metric extensions.geometry;
  covered boolean;
begin
  base := public.exposure_inputs_v021(lng,lat);
  metric := extensions.st_transform(
    extensions.st_setsrid(extensions.st_makepoint(lng,lat),4326),5186);
  select coalesce(extensions.st_covers(
    extensions.st_unaryunion(extensions.st_collect(d.geom)),
    extensions.st_transform(extensions.st_buffer(metric,90),4326)),false)
    into covered from public.admin_dongs d where left(d.adm_cd,5)='11680';
  return base || jsonb_build_object('schema_version','0.2.2',
    'coverage',(base->'coverage') || jsonb_build_object('score_ring_within_loaded_region',covered));
end;
$$;
revoke all on function public.exposure_inputs_v022(double precision,double precision) from public;
grant execute on function public.exposure_inputs_v022(double precision,double precision) to anon,authenticated;
