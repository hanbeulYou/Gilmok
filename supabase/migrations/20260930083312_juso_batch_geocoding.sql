-- Expand only. Existing Kakao rows/claims remain until an approved replacement manifest.
alter table ingest_private.geocode_requests
  drop constraint geocode_requests_provider_check;
alter table ingest_private.geocode_requests
  add constraint geocode_requests_provider_check check (provider in ('kakao','vworld','juso'));

alter table public.geocode_cache add column provenance jsonb;
comment on column public.geocode_cache.provenance is
  'Batch-only Juso identity and actual coordinate provider/CRS. Legacy rows remain NULL.';
revoke all on public.geocode_cache from public, anon, authenticated, service_role;
-- The Actions/direct DB owner is the sole shared-cache writer. No browser/server JWT RPC.
