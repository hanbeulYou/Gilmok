-- Retention serializes with real foreground activity and account promotion.
-- No deletion/schedule is enabled by this migration; existing activity dates stay intact.
insert into app_private.user_activity(user_id)
  select id from auth.users on conflict(user_id) do nothing;
create or replace function public.touch_user_activity() returns void
language plpgsql security definer set search_path='' as $$
begin
  if auth.uid() is null then raise exception 'authentication_required' using errcode='42501'; end if;
  perform 1 from auth.users where id=auth.uid() for update;
  if not found then raise exception 'authentication_required' using errcode='42501'; end if;
  insert into app_private.user_activity(user_id) values(auth.uid())
    on conflict(user_id) do update set last_active_at=now();
end $$;
revoke all on function public.touch_user_activity() from public,anon;
grant execute on function public.touch_user_activity() to authenticated;

create function app_private.track_owner_activity() returns trigger
language plpgsql security definer set search_path='' as $$
begin
  if auth.uid()=new.user_id then perform public.touch_user_activity(); end if;
  return new;
end $$;
revoke all on function app_private.track_owner_activity() from public,anon,authenticated;
create trigger candidate_owner_activity before insert or update on public.candidates
  for each row execute function app_private.track_owner_activity();
create trigger comparison_owner_activity before insert or update on public.comparisons
  for each row execute function app_private.track_owner_activity();
create trigger weight_preset_owner_activity before insert or update on public.user_weight_presets
  for each row execute function app_private.track_owner_activity();
create index user_activity_last_active_at_idx on app_private.user_activity(last_active_at);
create index comparisons_owner_updated_at_idx on public.comparisons(user_id,updated_at desc);
create index candidates_owner_updated_at_idx on public.candidates(user_id,updated_at desc);
notify pgrst,'reload schema';
