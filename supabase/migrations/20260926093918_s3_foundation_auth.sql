-- Anonymous Auth users are authenticated-role users; ownership survives email linking.
create table public.comparisons (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null default auth.uid() references auth.users(id) on delete cascade,
  candidate_ids uuid[] not null,
  weights jsonb not null check (jsonb_typeof(weights) = 'object'),
  preset_id text not null check (length(btrim(preset_id)) > 0),
  created_at timestamptz not null default now(),
  check (cardinality(candidate_ids) between 1 and 5),
  check (array_ndims(candidate_ids) = 1 and array_position(candidate_ids, null) is null)
);
create index comparisons_user_id_idx on public.comparisons(user_id);
alter table public.comparisons enable row level security;
revoke all on public.comparisons from public, anon, authenticated;
grant select, insert, update, delete on public.comparisons to authenticated;
create policy comparisons_owner on public.comparisons to authenticated
  using ((select auth.uid()) = user_id)
  with check ((select auth.uid()) = user_id);

create function ingest_private.check_comparison_candidates() returns trigger
language plpgsql security invoker set search_path = '' as $$
begin
  if (select count(distinct id) from unnest(new.candidate_ids) id)
       <> cardinality(new.candidate_ids)
     or (select count(*) from public.candidates c
         where c.id = any(new.candidate_ids) and c.user_id = new.user_id)
       <> cardinality(new.candidate_ids) then
    raise exception using errcode = '23514', message = 'comparison_candidates_not_owned';
  end if;
  return new;
end;
$$;
revoke all on function ingest_private.check_comparison_candidates() from public, anon, authenticated;
create trigger check_comparison_candidates before insert or update on public.comparisons
for each row execute function ingest_private.check_comparison_candidates();

-- Private counters cannot be edited or read through the Data API.
create table ingest_private.address_daily_usage (
  user_id uuid not null references auth.users(id) on delete cascade,
  day_kst date not null,
  request_count integer not null check (request_count between 1 and 10),
  primary key (user_id, day_kst)
);
revoke all on ingest_private.address_daily_usage from public, anon, authenticated;
alter table ingest_private.building_address_requests
  add column requester_uid uuid references auth.users(id) on delete set null;

create function ingest_private.identify_address_request() returns trigger
language plpgsql security definer set search_path = '' as $$
begin
  if new.status <> 'pending' then return new; end if;
  if tg_op = 'UPDATE' and old.status = 'pending' then return new; end if;
  if auth.uid() is null and not (
    coalesce(auth.role(), '') = 'service_role'
    or (session_user in ('postgres', 'supabase_admin')
        and coalesce(current_setting('role', true), 'none') in ('none', 'postgres'))
  ) then
    raise exception using errcode = '42501', message = 'address_request_requires_sign_in';
  end if;
  new.requester_uid := auth.uid();
  return new;
end;
$$;

create function ingest_private.limit_address_request() returns trigger
language plpgsql security definer set search_path = '' as $$
declare counted integer;
begin
  if new.status <> 'pending' then return new; end if;
  if tg_op = 'UPDATE' and old.status = 'pending' then return new; end if;
  if auth.uid() is null or coalesce(auth.jwt()->>'is_anonymous', 'false') <> 'true'
    then return new; end if;
  -- AFTER INSERT/UPDATE counts only an actual job, not ON CONFLICT no-ops.
  -- This row lock serializes concurrent requests; the 11th rolls back its queue row.
  insert into ingest_private.address_daily_usage(user_id, day_kst, request_count)
  values(auth.uid(), (statement_timestamp() at time zone 'Asia/Seoul')::date, 1)
  on conflict (user_id, day_kst) do update
    set request_count = address_daily_usage.request_count + 1
    where address_daily_usage.request_count < 10
  returning request_count into counted;
  if counted is null then
    raise exception using errcode = 'P0001', message = 'address_request_daily_limit';
  end if;
  return new;
end;
$$;
revoke all on function ingest_private.identify_address_request() from public, anon, authenticated;
revoke all on function ingest_private.limit_address_request() from public, anon, authenticated;
create trigger identify_address_request before insert or update of status
on ingest_private.building_address_requests for each row
execute function ingest_private.identify_address_request();
create trigger limit_address_request after insert or update of status
on ingest_private.building_address_requests for each row
execute function ingest_private.limit_address_request();

-- Rollback: disable the app/worker, then use a new migration to remove these triggers.
-- Preserve comparisons and usage rows until explicitly approved to remove them.
