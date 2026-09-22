-- MANUAL ONLY after remote cutover. This file is NOT a migration and is not auto-applied.
-- First create Vault secret gilmok_github_dispatch_token in the Dashboard, without logging it.
-- Fine-grained token: selected Gilmok repository, Contents: write (dispatch API requirement).
-- Enable pg_net via Dashboard first. No public schema table or trigger is exposed.
begin;
create or replace function ingest_private.wake_address_worker()
returns trigger language plpgsql security definer set search_path='' as $$
declare dispatch_token text;
begin
  if new.status <> 'pending' then return new; end if;
  if tg_op='UPDATE' then
    if old.status='pending' then return new; end if;
  end if;
  select decrypted_secret into dispatch_token from vault.decrypted_secrets
    where name='gilmok_github_dispatch_token';
  if dispatch_token is null then
    raise warning 'Address wake-up token missing; hourly sweep will recover pending work';
    return new;
  end if;
  perform net.http_post(
    url:='https://api.github.com/repos/hanbeulYou/Gilmok/dispatches',
    headers:=jsonb_build_object('Authorization','Bearer '||dispatch_token,
      'Accept','application/vnd.github+json','Content-Type','application/json'),
    body:='{"event_type":"gilmok_address_pending","client_payload":{"source":"supabase_queue"}}'::jsonb,
    timeout_milliseconds:=5000);
  return new;
exception when others then
  -- Queue insertion must survive webhook outage; never log SQLERRM, token or address.
  raise warning 'Address wake-up enqueue failed; pending preserved for hourly sweep';
  return new;
end $$;
revoke all on function ingest_private.wake_address_worker() from public,anon,authenticated;
drop trigger if exists gilmok_address_dispatch on ingest_private.building_address_requests;
create trigger gilmok_address_dispatch after insert or update of status
  on ingest_private.building_address_requests for each row
  execute function ingest_private.wake_address_worker();
commit;
-- Disable: DROP TRIGGER gilmok_address_dispatch ON ingest_private.building_address_requests;
