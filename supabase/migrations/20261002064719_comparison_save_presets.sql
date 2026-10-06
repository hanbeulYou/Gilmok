-- Expand existing owner tables; no existing rows are deleted or backfilled.
alter table public.candidates
  add column registration_context jsonb,
  add column lookup_request_id uuid,
  add column lookup_status text;
alter table public.comparisons
  add column preset_version text not null default '0.3',
  add column reference_snapshot text,
  add column manual_order boolean not null default false,
  add column updated_at timestamptz not null default now();

create function app_private.valid_weights(value jsonb, allow_zero boolean default true)
returns boolean language sql immutable set search_path='' as $$
  select case when jsonb_typeof(value) is distinct from 'object' then false else
    (select count(*)=8 and bool_and(k=any(array['demand','flow','transit','cluster',
      'exposure','building','environment','rent_efficiency']))
      and bool_and(case when jsonb_typeof(v)='number' then (v::text)::numeric between 0 and 40 else false end)
      and (allow_zero or sum(case when jsonb_typeof(v)='number' then (v::text)::numeric else 0 end)>0)
     from jsonb_each(value) e(k,v)) end;
$$;
create function app_private.normalized_weights(value jsonb)
returns jsonb language sql immutable set search_path='' as $$
  select jsonb_object_agg(k,case when total>0 then n/total else 0 end)
  from (select k,(v::text)::numeric n,sum((v::text)::numeric) over() total
    from jsonb_each(value) e(k,v)) s;
$$;
revoke all on function app_private.valid_weights(jsonb,boolean), app_private.normalized_weights(jsonb) from public,anon,authenticated;
-- Stored generated/check expressions execute as the writer; schema remains private.
grant execute on function app_private.valid_weights(jsonb,boolean), app_private.normalized_weights(jsonb) to authenticated;

create table public.user_weight_presets (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null default auth.uid() references auth.users(id) on delete cascade,
  name text not null check (char_length(btrim(name)) between 1 and 30 and name=btrim(name)),
  weights jsonb not null check (app_private.valid_weights(weights,false)),
  normalized_weights jsonb generated always as (app_private.normalized_weights(weights)) stored,
  preset_id text not null default 'academy_v0' check (preset_id='academy_v0'),
  preset_version text not null default '0.3' check (preset_version='0.3'),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique(user_id,name)
);
alter table public.user_weight_presets enable row level security;
revoke all on public.user_weight_presets from public,anon,authenticated;
grant select,insert,update,delete on public.user_weight_presets to authenticated;
create policy weight_presets_owner on public.user_weight_presets to authenticated
  using ((select auth.uid())=user_id) with check ((select auth.uid())=user_id);

create function app_private.stamp_updated_at() returns trigger
language plpgsql set search_path='' as $$ begin new.updated_at=now(); return new; end $$;
revoke all on function app_private.stamp_updated_at() from public,anon,authenticated;
create trigger candidate_updated_at before update on public.candidates
  for each row execute function app_private.stamp_updated_at();
create trigger comparison_updated_at before update on public.comparisons
  for each row execute function app_private.stamp_updated_at();
create trigger weight_preset_updated_at before update on public.user_weight_presets
  for each row execute function app_private.stamp_updated_at();

-- A candidate may belong to several owned comparisons. Removal cannot leave IDs behind.
create function app_private.remove_comparison_candidate() returns trigger
language plpgsql security definer set search_path='' as $$
begin
  delete from public.comparisons where user_id=old.user_id and candidate_ids=array[old.id];
  update public.comparisons set candidate_ids=array_remove(candidate_ids,old.id)
    where user_id=old.user_id and old.id=any(candidate_ids);
  return old;
end $$;
revoke all on function app_private.remove_comparison_candidate() from public,anon,authenticated;
create trigger remove_comparison_candidate after delete on public.candidates
  for each row execute function app_private.remove_comparison_candidate();

-- All writes share one transaction. Caller-supplied IDs are stable for safe retry,
-- but never confer ownership. Existing RLS/direct-table contracts remain available.
create function public.save_comparison(comparison_id uuid, candidate_rows jsonb,
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
      reference_snapshot=excluded.reference_snapshot,manual_order=excluded.manual_order
    where c.user_id=owner_id returning id into saved;
  if saved is null then raise exception 'comparison_not_owned' using errcode='42501'; end if;
  return saved;
end $$;

create function public.load_comparison(comparison_id uuid default null) returns jsonb
language sql stable security invoker set search_path='' as $$
  select jsonb_build_object('comparison',to_jsonb(c),'candidates',(
    select jsonb_agg((to_jsonb(v)-'geom')||jsonb_build_object('lat',extensions.st_y(v.geom),'lng',extensions.st_x(v.geom))
      order by array_position(c.candidate_ids,v.id)) from public.candidates v where v.id=any(c.candidate_ids)))
  from public.comparisons c where c.user_id=auth.uid() and (comparison_id is null or c.id=comparison_id)
  order by c.updated_at desc,c.id limit 1;
$$;
revoke all on function public.save_comparison(uuid,jsonb,jsonb,uuid[],boolean,text),public.load_comparison(uuid) from public,anon;
grant execute on function public.save_comparison(uuid,jsonb,jsonb,uuid[],boolean,text),public.load_comparison(uuid) to authenticated;
notify pgrst,'reload schema';
