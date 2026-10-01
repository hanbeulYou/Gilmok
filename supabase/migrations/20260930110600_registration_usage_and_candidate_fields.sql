-- Additive registration metadata. Existing candidates/RLS remain valid.
alter table public.candidates
  add column address text,
  add column alias text check (char_length(alias) <= 20),
  add column pnu text check (pnu ~ '^[0-9]{19}$'),
  add column address_provenance jsonb,
  add column updated_at timestamptz not null default now();

create schema if not exists app_private;
revoke all on schema app_private from public, anon, authenticated;
create table app_private.address_daily_usage (
  user_id uuid not null references auth.users(id) on delete cascade,
  day_kst date not null,
  total integer not null check (total between 1 and 100),
  juso_search integer not null default 0,
  vworld_coordinate integer not null default 0,
  primary key (user_id, day_kst)
);
create table app_private.user_activity (
  user_id uuid primary key references auth.users(id) on delete cascade,
  last_active_at timestamptz not null default now()
);
-- Start the retention clock conservatively for existing accounts; deletion is PR C.
insert into app_private.user_activity(user_id) select id from auth.users;
alter table app_private.address_daily_usage enable row level security;
alter table app_private.user_activity enable row level security;
revoke all on app_private.address_daily_usage, app_private.user_activity
  from public, anon, authenticated, service_role;

create function public.touch_user_activity() returns void
language plpgsql security definer set search_path='' as $$
begin
  if auth.uid() is null then raise exception 'authentication_required' using errcode='42501'; end if;
  insert into app_private.user_activity(user_id) values(auth.uid())
  on conflict(user_id) do update set last_active_at=now();
end; $$;

-- Reserve before external IO. Concurrent requests cannot exceed the daily limit;
-- failures still consume a reservation, so retries cannot bypass the limit.
create function public.claim_address_call(provider text) returns boolean
language plpgsql security definer set search_path='' as $$
declare accepted integer;
begin
  if auth.uid() is null then raise exception 'authentication_required' using errcode='42501'; end if;
  if provider is null or provider not in ('juso_search','vworld_coordinate') then
    raise exception 'invalid_address_provider' using errcode='22023';
  end if;
  insert into app_private.address_daily_usage as u(user_id,day_kst,total,juso_search,vworld_coordinate)
  values(auth.uid(),(now() at time zone 'Asia/Seoul')::date,1,
    (provider='juso_search')::integer,(provider='vworld_coordinate')::integer)
  on conflict(user_id,day_kst) do update set total=u.total+1,
    juso_search=u.juso_search+excluded.juso_search,
    vworld_coordinate=u.vworld_coordinate+excluded.vworld_coordinate
  where u.total<100 returning total into accepted;
  if accepted is not null then perform public.touch_user_activity(); end if;
  return accepted is not null;
end; $$;
revoke all on function public.touch_user_activity(), public.claim_address_call(text) from public,anon;
grant execute on function public.touch_user_activity(), public.claim_address_call(text) to authenticated;
-- Rollback: roll back app first, revoke the new RPCs; retain owner metadata/usage.
