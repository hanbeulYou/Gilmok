-- Keep applied migration immutable; disambiguate address parameter from conflict column.
create or replace function public.watch_candidate_lookup(address text) returns uuid
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
    on conflict on constraint candidate_lookup_watchers_user_id_address_key do update set user_id=excluded.user_id returning w.request_id into id;
  insert into public.candidate_lookup_status(request_id,status)
    values(id,app_private.current_lookup_status(normalized))
    on conflict(request_id) do update set status=excluded.status,updated_at=now();
  return id;
end; $$;
