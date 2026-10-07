-- Keep the legacy input/weight contract separate from the declared scoring model.
-- Old rows stay NULL; historical versions cannot be reconstructed from preset_version.
alter table public.comparisons add column scoring_model_version text
  constraint comparisons_scoring_model_version_check check (
    scoring_model_version is null or
    (length(scoring_model_version) <= 32 and scoring_model_version ~ '^[0-9]+[.][0-9]+([.][0-9]+)?$')
  );
comment on column public.comparisons.scoring_model_version is
  'Client-declared model for the saved comparison; NULL means unrecorded or incomplete scoring. Not preset input-contract version.';

-- Preserve signature, grants and atomic save; legacy writers invalidate any old model tag.
create or replace function public.save_comparison(comparison_id uuid, candidate_rows jsonb,
  raw_weights jsonb, ordered_ids uuid[], fixed_order boolean default false,
  source_snapshot text default null) returns uuid
language plpgsql security definer set search_path='' as $$
declare owner_id uuid:=auth.uid(); r jsonb; saved uuid; ids uuid[]; n integer;
begin
  if owner_id is null then raise exception 'authentication_required' using errcode='42501'; end if;
  perform public.touch_user_activity();
  if comparison_id is null or jsonb_typeof(candidate_rows) is distinct from 'array'
     or not app_private.valid_weights(raw_weights,true) then
    raise exception 'invalid_comparison' using errcode='22023';
  end if;
  n=jsonb_array_length(candidate_rows);
  select array_agg((item->>'id')::uuid) into ids from jsonb_array_elements(candidate_rows) item;
  if n not between 1 and 5 or cardinality(ordered_ids) is distinct from n
    or array_ndims(ordered_ids) is distinct from 1
    or (select count(distinct x) from unnest(ids) x)<>n
    or (select count(distinct x) from unnest(ordered_ids) x)<>n
    or not (ids @> ordered_ids and ordered_ids @> ids) then
    raise exception 'invalid_candidate_order' using errcode='22023';
  end if;
  if exists(select 1 from public.comparisons where id=comparison_id and user_id<>owner_id) then
    raise exception 'comparison_not_owned' using errcode='42501';
  end if;
  for r in select * from jsonb_array_elements(candidate_rows) loop
    if (r->>'floor')::integer not between -5 and 30 or (r->>'floor')::integer=0
      or r->>'floor' is null or (r->>'lat')::float8 not between -90 and 90
      or (r->>'lng')::float8 not between -180 and 180 or r->>'lat' is null or r->>'lng' is null
      or length(btrim(r->>'alias')) not between 1 and 20 or r->>'alias' is null
      or length(r->>'address') not between 1 and 200 or r->>'address' is null
      or jsonb_typeof(r->'registration_context') is distinct from 'object'
      or jsonb_typeof(r->'address_provenance') is distinct from 'object'
      or octet_length(r::text)>100000 then
      raise exception 'invalid_candidate' using errcode='22023';
    end if;
    if nullif(r->>'lookup_request_id','') is not null and not exists(
      select 1 from app_private.candidate_lookup_watchers s where s.request_id=(r->>'lookup_request_id')::uuid
        and s.user_id=owner_id) then
      raise exception 'lookup_not_owned' using errcode='42501';
    end if;
    insert into public.candidates as c(id,user_id,geom,floor,deposit,user_rent,management_fee,area_m2,
      address,alias,pnu,address_provenance,registration_context,lookup_request_id,lookup_status)
    values((r->>'id')::uuid,owner_id,extensions.st_setsrid(extensions.st_makepoint((r->>'lng')::float8,(r->>'lat')::float8),4326),
      (r->>'floor')::integer,(r->>'deposit')::numeric,(r->>'user_rent')::numeric,(r->>'management_fee')::numeric,
      (r->>'area_m2')::numeric,r->>'address',btrim(r->>'alias'),r->>'pnu',r->'address_provenance',
      r->'registration_context',nullif(r->>'lookup_request_id','')::uuid,r->>'lookup_status')
    on conflict(id) do update set geom=excluded.geom,floor=excluded.floor,deposit=excluded.deposit,
      user_rent=excluded.user_rent,management_fee=excluded.management_fee,area_m2=excluded.area_m2,
      address=excluded.address,alias=excluded.alias,pnu=excluded.pnu,address_provenance=excluded.address_provenance,
      registration_context=excluded.registration_context,lookup_request_id=excluded.lookup_request_id,lookup_status=excluded.lookup_status
    where c.user_id=owner_id returning id into saved;
    if saved is null then raise exception 'candidate_not_owned' using errcode='42501'; end if;
  end loop;
  insert into public.comparisons as c(id,user_id,candidate_ids,weights,preset_id,preset_version,reference_snapshot,manual_order)
    values(comparison_id,owner_id,ordered_ids,raw_weights,'academy_v0','0.3',source_snapshot,fixed_order)
    on conflict(id) do update set candidate_ids=excluded.candidate_ids,weights=excluded.weights,
      preset_id=excluded.preset_id,preset_version=excluded.preset_version,
      reference_snapshot=excluded.reference_snapshot,manual_order=excluded.manual_order,
      scoring_model_version=null
    where c.user_id=owner_id returning id into saved;
  if saved is null then raise exception 'comparison_not_owned' using errcode='42501'; end if;
  return saved;
end $$;

-- A distinct name avoids overload ambiguity for old PostgREST clients.
create function public.save_comparison_v2(comparison_id uuid, candidate_rows jsonb,
  raw_weights jsonb, ordered_ids uuid[], model_version text,
  fixed_order boolean default false, source_snapshot text default null)
returns uuid language plpgsql security definer set search_path='' as $$
declare saved uuid;
begin
  if auth.uid() is null then raise exception 'authentication_required' using errcode='42501'; end if;
  if model_version is not null and
    (length(model_version)>32 or model_version !~ '^[0-9]+[.][0-9]+([.][0-9]+)?$') then
    raise exception 'invalid_scoring_model_version' using errcode='22023';
  end if;
  saved:=public.save_comparison(comparison_id,candidate_rows,raw_weights,ordered_ids,fixed_order,source_snapshot);
  -- This is part of save consistency: failure must roll back candidates AND comparison.
  update public.comparisons c set scoring_model_version=model_version
    where c.id=saved and c.user_id=auth.uid();
  if not found then raise exception 'comparison_not_owned' using errcode='42501'; end if;
  return saved;
end;
$$;
revoke all on function public.save_comparison_v2(uuid,jsonb,jsonb,uuid[],text,boolean,text) from public,anon;
grant execute on function public.save_comparison_v2(uuid,jsonb,jsonb,uuid[],text,boolean,text) to authenticated;
notify pgrst, 'reload schema';
