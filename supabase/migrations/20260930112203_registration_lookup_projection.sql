-- PR A supplies the private watcher/state contract; subscription UI ships in B.
create table app_private.candidate_lookup_watchers (
  request_id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  address text not null references ingest_private.building_address_requests(address) on delete cascade,
  unique(user_id,address)
);
alter table app_private.candidate_lookup_watchers enable row level security;
revoke all on app_private.candidate_lookup_watchers from public,anon,authenticated,service_role;
create table public.candidate_lookup_status (
  request_id uuid primary key references app_private.candidate_lookup_watchers(request_id) on delete cascade,
  status text not null check(status in ('pending','processing','ready','not_found','ambiguous','failed')),
  updated_at timestamptz not null default now()
);
alter table public.candidate_lookup_status enable row level security;
revoke all on public.candidate_lookup_status from public,anon,authenticated,service_role;
grant select on public.candidate_lookup_status to authenticated;
create function public.owns_candidate_lookup(id uuid) returns boolean
language sql stable security definer set search_path='' as $$
  select exists(select 1 from app_private.candidate_lookup_watchers w
    where w.request_id=id and w.user_id=auth.uid());
$$;
revoke all on function public.owns_candidate_lookup(uuid) from public,anon;
grant execute on function public.owns_candidate_lookup(uuid) to authenticated;
create policy candidate_lookup_owner on public.candidate_lookup_status for select to authenticated
  using(public.owns_candidate_lookup(request_id));
create view public.candidate_lookup_state with (security_invoker=true) as
  select request_id,status,updated_at from public.candidate_lookup_status;
revoke all on public.candidate_lookup_state from public,anon;
grant select on public.candidate_lookup_state to authenticated;

create function app_private.current_lookup_status(requested_address text) returns text
language sql stable security definer set search_path='' as $$
  select coalesce(
    (select c.status from ingest_private.building_address_cache c
     where c.address=requested_address and c.expires_at>now()),
    (select case when r.status='done' then 'failed' else r.status end
     from ingest_private.building_address_requests r where r.address=requested_address));
$$;
revoke all on function app_private.current_lookup_status(text) from public,anon,authenticated;
create function public.watch_candidate_lookup(address text) returns uuid
language plpgsql security definer set search_path='' as $$
declare normalized text; id uuid;
begin
  if auth.uid() is null then raise exception 'authentication_required' using errcode='42501'; end if;
  normalized:=score_internal.normalize_building_address(address);
  if normalized is null then return null; end if;
  perform pg_advisory_xact_lock(hashtextextended(normalized,73201));
  if not exists(select 1 from ingest_private.building_address_requests r where r.address=normalized) then
    return null;
  end if;
  insert into app_private.candidate_lookup_watchers as w(user_id,address) values(auth.uid(),normalized)
    on conflict(user_id,address) do update set user_id=excluded.user_id returning w.request_id into id;
  insert into public.candidate_lookup_status(request_id,status)
    values(id,app_private.current_lookup_status(normalized))
    on conflict(request_id) do update set status=excluded.status,updated_at=now();
  return id;
end; $$;
revoke all on function public.watch_candidate_lookup(text) from public,anon;
grant execute on function public.watch_candidate_lookup(text) to authenticated;

create function app_private.refresh_candidate_lookup() returns trigger
language plpgsql security definer set search_path='' as $$
begin
  perform pg_advisory_xact_lock(hashtextextended(new.address,73201));
  update public.candidate_lookup_status s set status=app_private.current_lookup_status(new.address),
    updated_at=clock_timestamp() from app_private.candidate_lookup_watchers w
    where s.request_id=w.request_id and w.address=new.address;
  return null;
end; $$;
revoke all on function app_private.refresh_candidate_lookup() from public,anon,authenticated;
create trigger candidate_lookup_request_update after insert or update
  on ingest_private.building_address_requests for each row execute function app_private.refresh_candidate_lookup();
create trigger candidate_lookup_cache_update after insert or update
  on ingest_private.building_address_cache for each row execute function app_private.refresh_candidate_lookup();

-- Keep the existing implementation intact, including batch/anon behavior and precision.
alter function public.score_inputs(double precision,double precision,integer,integer,text) set schema score_internal;
alter function score_internal.score_inputs(double precision,double precision,integer,integer,text)
  rename to score_inputs_registration_base;
create function public.score_inputs(lat double precision,lng double precision,radius_m integer,
  floor integer,address text default null) returns jsonb
language plpgsql security invoker set search_path='' set extra_float_digits='3' as $$
declare result jsonb; request_id uuid;
begin
  result:=score_internal.score_inputs_registration_base(lat,lng,radius_m,floor,address);
  if auth.uid() is not null and result->'meta'->'building_lookup'->>'status' in ('pending','processing','failed') then
    request_id:=public.watch_candidate_lookup(result->'meta'->'building_lookup'->>'address');
    result:=jsonb_set(result,'{meta,building_lookup,request_id}',coalesce(to_jsonb(request_id),'null'::jsonb));
  end if;
  return result;
end; $$;
revoke all on function public.score_inputs(double precision,double precision,integer,integer,text) from public;
grant execute on function public.score_inputs(double precision,double precision,integer,integer,text) to anon,authenticated,service_role;

do $$ begin
  if exists(select 1 from pg_publication where pubname='supabase_realtime') then
    alter publication supabase_realtime add table public.candidate_lookup_status;
  end if;
end $$;
-- Rollback: stop B subscriptions, revoke watcher RPCs, drop wrapper and move/rename
-- score_internal.score_inputs_registration_base back; retain private mapping/history.
