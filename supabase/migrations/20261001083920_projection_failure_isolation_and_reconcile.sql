-- Forward-only fix: original migration 4 and the score_inputs contract stay intact.
create table app_private.projection_errors (
  id bigint generated always as identity primary key,
  occurred_at timestamptz not null default clock_timestamp(),
  source_table text not null,
  row_id text not null,
  sqlstate text not null check (char_length(sqlstate)=5),
  message text not null,
  resolved_at timestamptz
);
create index projection_errors_unresolved_idx on app_private.projection_errors(row_id)
  where resolved_at is null;
alter table app_private.projection_errors enable row level security;
revoke all on app_private.projection_errors from public,anon,authenticated,service_role;

-- Error logging is itself best effort: even an unavailable journal must not abort
-- the source write. No address or exception message is emitted into server logs.
create function app_private.record_projection_error(source_table text,row_id text,
  error_state text,error_message text) returns void
language plpgsql security definer set search_path='' set lock_timeout='250ms' as $$
begin
  begin
    insert into app_private.projection_errors(source_table,row_id,sqlstate,message)
      values(source_table,row_id,error_state,error_message);
  exception when others then
    raise warning 'projection_error_log_failed sqlstate=%',SQLSTATE;
  end;
end; $$;
revoke all on function app_private.record_projection_error(text,text,text,text)
  from public,anon,authenticated,service_role;

create or replace function app_private.refresh_candidate_lookup() returns trigger
language plpgsql security definer set search_path='' set lock_timeout='250ms' as $$
declare error_state text; error_message text;
begin
  begin
    perform pg_advisory_xact_lock(hashtextextended(new.address,73201));
    update public.candidate_lookup_status s
      set status=app_private.current_lookup_status(new.address),updated_at=clock_timestamp()
      from app_private.candidate_lookup_watchers w
      where s.request_id=w.request_id and w.address=new.address;
  exception when others then
    get stacked diagnostics error_state=RETURNED_SQLSTATE,error_message=MESSAGE_TEXT;
    perform app_private.record_projection_error(
      TG_TABLE_SCHEMA||'.'||TG_TABLE_NAME,new.address,error_state,error_message);
  end;
  return new;
end; $$;
-- Both existing bindings already are AFTER INSERT OR UPDATE triggers.

create function app_private.reconcile_candidate_lookup(do_apply boolean default true)
returns jsonb language plpgsql security definer set search_path='' set lock_timeout='250ms' as $$
declare item record; expected text; scanned bigint; mismatched bigint;
  repaired bigint:=0; resolved bigint:=0; affected bigint; fixed bigint; failed_addresses bigint:=0;
  unresolved_before bigint; unresolved_after bigint; error_state text; error_message text;
begin
  if do_apply is null then raise exception 'invalid_projection_reconcile_mode'; end if;
  select count(*),count(*) filter(where s.status is distinct from app_private.current_lookup_status(w.address))
    into scanned,mismatched from app_private.candidate_lookup_watchers w
    left join public.candidate_lookup_status s using(request_id);
  select count(*) into unresolved_before from app_private.projection_errors where resolved_at is null;
  if do_apply then
    for item in
      select address from app_private.candidate_lookup_watchers
      union select row_id as address from app_private.projection_errors where resolved_at is null
      order by address
    loop
      begin
        perform pg_advisory_xact_lock(hashtextextended(item.address,73201));
        expected:=app_private.current_lookup_status(item.address);
        insert into public.candidate_lookup_status as s(request_id,status)
          select request_id,expected from app_private.candidate_lookup_watchers where address=item.address
          on conflict(request_id) do update set status=excluded.status,updated_at=clock_timestamp()
          where s.status is distinct from excluded.status;
        get diagnostics fixed=ROW_COUNT;
        update app_private.projection_errors set resolved_at=clock_timestamp()
          where row_id=item.address and resolved_at is null;
        get diagnostics affected=ROW_COUNT;
        repaired:=repaired+fixed;
        resolved:=resolved+affected;
      exception when others then
        failed_addresses:=failed_addresses+1;
        get stacked diagnostics error_state=RETURNED_SQLSTATE,error_message=MESSAGE_TEXT;
        perform app_private.record_projection_error(
          'public.candidate_lookup_status',item.address,error_state,error_message);
      end;
    end loop;
  end if;
  select count(*) into unresolved_after from app_private.projection_errors where resolved_at is null;
  return jsonb_build_object('dry_run',not do_apply,'scanned',scanned,'mismatched',mismatched,
    'repaired',repaired,'errors_resolved',resolved,'failed_addresses',failed_addresses,
    'unresolved_before',unresolved_before,'unresolved_errors',unresolved_after);
end; $$;
revoke all on function app_private.reconcile_candidate_lookup(boolean)
  from public,anon,authenticated,service_role;
-- Sweep uses the existing batch DB connection as migration owner. No new API grant.
-- Rollback of PR A: remove the two source triggers and restore score_inputs as documented;
-- keep error/history tables. Do not restore the unsafe trigger implementation.
