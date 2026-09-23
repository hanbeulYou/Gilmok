-- Preserve double precision through PostgREST; rounded table JSON breaks percentile ties.
-- Read-only SECURITY INVOKER uses existing SELECT-only RLS, never promotes a snapshot.
create function public.score_reference_distribution(requested_preset_id text, requested_radius_m integer)
returns jsonb language plpgsql stable security invoker
set search_path='' set extra_float_digits='3' as $$
begin
  if requested_radius_m is null or requested_radius_m not in (800,1000) then
    raise exception 'unsupported reference radius' using errcode='22023';
  end if;
  return (
    select jsonb_build_object(
      'preset',jsonb_build_object('id',s.preset_id,'version',s.preset_version),
      'inputs_schema_version',s.inputs_schema_version,'snapshot',s.snapshot,
      'source_fingerprint',s.source_fingerprint,'sources',s.source_versions->'sources',
      'distributions',coalesce((select jsonb_agg(jsonb_build_object(
        'radius_m',q.radius_m,'key',q.axis_key,'cell_count',s.cell_count,'values',q.values)
        order by q.axis_key) from (
          select r.radius_m,r.axis_key,coalesce(jsonb_agg(r.raw_value order by r.raw_value)
            filter(where r.raw_value is not null),'[]'::jsonb) as values
          from public.score_reference r where r.preset_id=s.preset_id
            and r.preset_version=s.preset_version and r.snapshot=s.snapshot
            and r.radius_m=requested_radius_m group by r.radius_m,r.axis_key
        ) q),'[]'::jsonb))
    from public.score_reference_sets s where s.preset_id=requested_preset_id
  );
end;
$$;
revoke all on function public.score_reference_distribution(text,integer) from public;
grant execute on function public.score_reference_distribution(text,integer) to anon,authenticated,service_role;
comment on function public.score_reference_distribution(text,integer) is
  'Read reference/context injection data with exact double precision. Use this RPC rather than rounded table JSON for tie-sensitive scoring.';
