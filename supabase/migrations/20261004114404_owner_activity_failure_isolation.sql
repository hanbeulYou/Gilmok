-- Ancillary activity writes fail open; authentication and deletion integrity stay strict.
create or replace function public.touch_user_activity() returns void
language plpgsql security definer set search_path='' as $$
declare owner_id uuid:=auth.uid(); error_state text; error_message text;
begin
 if owner_id is null then
   raise exception 'authentication_required' using errcode='42501';
 end if;
 perform 1 from auth.users where id=owner_id for update;
 if not found then raise exception 'authentication_required' using errcode='42501'; end if;
 begin
   insert into app_private.user_activity(user_id) values(owner_id)
   on conflict(user_id) do update set last_active_at=now();
   update app_private.projection_errors set resolved_at=clock_timestamp()
   where source_table='app_private.user_activity' and row_id=owner_id::text
     and resolved_at is null;
 exception when others then
   get stacked diagnostics error_state=RETURNED_SQLSTATE,error_message=MESSAGE_TEXT;
   perform app_private.record_projection_error(
     'app_private.user_activity',owner_id::text,error_state,error_message);
 end;
end $$;

create or replace function app_private.track_owner_activity() returns trigger
language plpgsql security definer set search_path='' set lock_timeout='250ms' as $$
declare error_state text; error_message text;
begin
 begin
   if auth.uid()=new.user_id then perform public.touch_user_activity(); end if;
 exception when others then
   get stacked diagnostics error_state=RETURNED_SQLSTATE,error_message=MESSAGE_TEXT;
   perform app_private.record_projection_error(
     'app_private.user_activity',new.user_id::text,error_state,error_message);
 end;
 return new;
end $$;

drop trigger candidate_owner_activity on public.candidates;
drop trigger comparison_owner_activity on public.comparisons;
drop trigger weight_preset_owner_activity on public.user_weight_presets;
create trigger candidate_owner_activity after insert or update on public.candidates
for each row execute function app_private.track_owner_activity();
create trigger comparison_owner_activity after insert or update on public.comparisons
for each row execute function app_private.track_owner_activity();
create trigger weight_preset_owner_activity after insert or update on public.user_weight_presets
for each row execute function app_private.track_owner_activity();
-- stamp_updated_at BEFORE and remove_comparison_candidate AFTER stay unchanged/strict.
notify pgrst,'reload schema';
