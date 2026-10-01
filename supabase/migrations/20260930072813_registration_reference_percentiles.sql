-- Additive transport: retain the full-distribution RPC for batch/replay readers.
-- Rollback: revoke this RPC and roll back the application adapter; no data changes.
create function public.score_reference_percentiles(
  requested_preset_id text, requested_radius_m integer, requested_raw jsonb
) returns jsonb language plpgsql stable security invoker
set search_path = '' set extra_float_digits = '3' as $$
declare
  item record;
  numeric_raw double precision;
  allowed_keys constant text[] := array['demand','flow','transit.nearest_subway_m',
    'transit.subway_boardings_golden','transit.bus_stops','cluster.saturation',
    'environment.stores_total'];
begin
  if requested_radius_m is null or requested_radius_m not in (800,1000)
    or requested_raw is null or jsonb_typeof(requested_raw) <> 'object' then
    raise exception 'invalid_percentile_request' using errcode='22023';
  end if;
  if (select count(*) from jsonb_object_keys(requested_raw)) not between 1 and 7 then
    raise exception 'invalid_percentile_keys' using errcode='22023';
  end if;
  for item in select key,value from jsonb_each(requested_raw) loop
    if not (item.key = any(allowed_keys)) or jsonb_typeof(item.value) not in ('number','null') then
      raise exception 'invalid_percentile_raw' using errcode='22023';
    end if;
    numeric_raw := (item.value #>> '{}')::double precision;
    if numeric_raw < 0 or numeric_raw >= 'Infinity'::double precision then
      raise exception 'invalid_percentile_raw' using errcode='22023';
    end if;
  end loop;
  return (
    select jsonb_build_object('kind','percentiles',
      'preset',jsonb_build_object('id',s.preset_id,'version',s.preset_version),
      'inputs_schema_version',s.inputs_schema_version,'snapshot',s.snapshot,
      'source_fingerprint',s.source_fingerprint,'sources',s.source_versions->'sources',
      'percentiles',coalesce((
        select jsonb_agg(jsonb_build_object('radius_m',requested_radius_m,'key',q.key,
          'raw',q.raw,'cell_count',s.cell_count,'population_size',stats.n,
          'percentile',case when q.raw is null or stats.n=0 then null else
            100::double precision * (stats.less::double precision +
              case when stats.equal=0 then 0 else (stats.equal::double precision+1)/2 end)
              / stats.n::double precision end,
          'histogram',jsonb_build_object('min',stats.lo,'max',stats.hi,'bins',
            case when stats.n=0 then '[]'::jsonb else (
              select jsonb_agg(coalesce(counts.n,0) order by bins.bin)
              from generate_series(1,20) bins(bin) left join (
                select case when stats.lo=stats.hi then 1
                  else least(20,width_bucket(r.raw_value,stats.lo,stats.hi,20)) end bin,
                  count(*) n
                from public.score_reference r where r.preset_id=s.preset_id
                  and r.preset_version=s.preset_version and r.snapshot=s.snapshot
                  and r.radius_m=requested_radius_m and r.axis_key=q.key
                  and r.raw_value is not null group by 1
              ) counts using(bin)
            ) end)) order by q.key)
        from (select key,(value #>> '{}')::double precision raw from jsonb_each(requested_raw)) q
        cross join lateral (
          select count(*) n,min(r.raw_value) lo,max(r.raw_value) hi,
            count(*) filter(where r.raw_value<q.raw) less,
            count(*) filter(where r.raw_value=q.raw) equal
          from public.score_reference r where r.preset_id=s.preset_id
            and r.preset_version=s.preset_version and r.snapshot=s.snapshot
            and r.radius_m=requested_radius_m and r.axis_key=q.key and r.raw_value is not null
        ) stats
        where exists(select 1 from public.score_reference r where r.preset_id=s.preset_id
          and r.preset_version=s.preset_version and r.snapshot=s.snapshot
          and r.radius_m=requested_radius_m and r.axis_key=q.key)
      ),'[]'::jsonb)) from public.score_reference_sets s where s.preset_id=requested_preset_id
  );
end;
$$;
revoke all on function public.score_reference_percentiles(text,integer,jsonb) from public,anon;
grant execute on function public.score_reference_percentiles(text,integer,jsonb) to authenticated,service_role;
comment on function public.score_reference_percentiles(text,integer,jsonb) is
  'v0.3 transport only: float8 average 1-based tie ranks; no raw distribution download. Histogram has 20 equal-width bins; final bin includes max; constant populations use bin 1.';
