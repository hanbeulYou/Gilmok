-- Additive: two private metadata tables and one authenticated read-only RPC.
-- No existing objects/rows changed. G's display tables may not be installed yet.
create table app_private.academy_coordinate_reviews (
  entity_kind text not null check (entity_kind in ('academy','school')),
  entity_id text not null,
  source_revision text not null,
  source_raw_sha256 text not null check (source_raw_sha256 ~ '^[0-9a-f]{64}$'),
  review_version text not null,
  reason_code text not null check (reason_code='movement_gt_500m'),
  primary key(entity_kind,entity_id,review_version)
);
create table app_private.academy_layer_release (
  singleton boolean primary key default true check(singleton),
  source_revision text not null,
  raw_sha256 text not null check (raw_sha256 ~ '^[0-9a-f]{64}$'),
  academy_source jsonb not null check(jsonb_typeof(academy_source)='object'),
  review_version text not null,
  reviewed_academy_count integer not null check(reviewed_academy_count>=0),
  reviewed_school_count integer not null check(reviewed_school_count>=0)
);
alter table app_private.academy_coordinate_reviews enable row level security;
alter table app_private.academy_layer_release enable row level security;
revoke all on app_private.academy_coordinate_reviews,app_private.academy_layer_release
  from public,anon,authenticated;
comment on table app_private.academy_layer_release is
  'No automatic activation. G must publish source/display/reviews/reference and this gate atomically.';

create function public.academy_layer(
  lat double precision,lng double precision,radius_m integer,
  requested_field text,expected_source jsonb
) returns jsonb language plpgsql stable security definer
set search_path='' set extra_float_digits='3' as $$
declare
  center extensions.geometry;
  source_meta jsonb;
  source_rows integer;
  release app_private.academy_layer_release%rowtype;
  display_release record;
  response jsonb;
  payload jsonb;
  invalid_display boolean;
  academy_reviews integer;
  school_reviews integer;
begin
  if auth.uid() is null then
    raise exception 'authentication_required' using errcode='42501';
  end if;
  if lat is null or lng is null or not(lat between 33 and 39 and lng between 124 and 132)
    or radius_m is null or radius_m not in (800,1000)
    or requested_field is null or char_length(requested_field)>200
    or expected_source is null or jsonb_typeof(expected_source)<>'object' then
    raise exception 'invalid_academy_layer_input' using errcode='22023';
  end if;
  center:=extensions.st_setsrid(extensions.st_makepoint(lng,lat),4326);
  response:=jsonb_build_object('schema_version','1.0','status','coordinate_replacement_pending',
    'center',jsonb_build_array(lng,lat),'radius_m',radius_m,'field',requested_field,
    'collection',null,'counts',null,'meta',null);
  if not exists(select 1 from public.admin_dongs d
    where left(d.adm_cd,2)='11' and extensions.st_covers(d.geom,center)) then
    return response||jsonb_build_object('status','outside_coverage','reason','outside_coverage');
  end if;
  -- Exact academies member of score_internal.sources(), without scanning unrelated sources.
  select jsonb_build_object('source',s.source,'source_version',s.source_version,
    'reference_date',s.source_version,'date_kind','snapshot','period_start',null,
    'period_end',null,'quarter',null,'ingested_at',s.ingested_at,'coverage','Seoul',
    'available',true,'unlocated_count',s.row_count-s.located_count,
    'limitations',case when s.row_count>s.located_count
      then jsonb_build_array('unlocated_records_not_in_spatial_counts') else '[]'::jsonb end),
    s.row_count into source_meta,source_rows
    from ingest_private.place_snapshots s where s.target_table='academies';
  if source_meta is null then
    return response||jsonb_build_object('reason','source_missing');
  end if;
  if source_meta is distinct from expected_source then
    return response||jsonb_build_object('status','source_mismatch','reason','source_changed');
  end if;
  if to_regclass('app_private.academy_display') is null
    or to_regclass('app_private.academy_display_release') is null then
    return response||jsonb_build_object('reason','release_missing');
  end if;
  select * into release from app_private.academy_layer_release where singleton;
  if not found then return response||jsonb_build_object('reason','release_missing'); end if;
  select * into display_release from app_private.academy_display_release where singleton;
  if not found then return response||jsonb_build_object('reason','release_missing'); end if;
  if release.academy_source is distinct from source_meta
    or release.source_revision<>display_release.source_revision
    or release.raw_sha256<>display_release.raw_sha256
    or display_release.source_version<>source_meta->>'source_version'
    or display_release.coordinate_provider<>'juso'
    or display_release.row_count<>source_rows then
    return response||jsonb_build_object('status','source_mismatch','reason','release_mismatch');
  end if;
  select count(*) filter(where q.entity_kind='academy'),
         count(*) filter(where q.entity_kind='school')
    into academy_reviews,school_reviews from app_private.academy_coordinate_reviews q
    where q.review_version=release.review_version;
  if academy_reviews<>release.reviewed_academy_count
    or school_reviews<>release.reviewed_school_count
    or exists(select 1 from app_private.academy_coordinate_reviews q
      where q.entity_kind='academy' and q.review_version=release.review_version
        and (q.source_revision<>release.source_revision or q.source_raw_sha256<>release.raw_sha256)) then
    return response||jsonb_build_object('status','source_mismatch','reason','quality_review_mismatch');
  end if;

  with nearby as materialized (
    select a.id,a.name,a.field,a.geom,a.geocode_provider,
      d.floor_label,d.floor_status,d.source_revision,d.raw_sha256,
      q.reason_code,q.review_version
    from public.academies a
    left join app_private.academy_display d on d.academy_id=a.id
    left join app_private.academy_coordinate_reviews q on q.entity_kind='academy'
      and q.entity_id=a.id and q.review_version=release.review_version
      and q.source_revision=release.source_revision and q.source_raw_sha256=release.raw_sha256
    where a.registration_status='개원'
      and extensions.st_dwithin(a.geom::extensions.geography,center::extensions.geography,radius_m)
  ), fields as (select field,count(*) n from nearby group by field)
  select coalesce(bool_or(n.source_revision is distinct from release.source_revision
      or n.raw_sha256 is distinct from release.raw_sha256
      or n.geocode_provider is distinct from 'juso'),false),
    jsonb_build_object('counts',jsonb_build_object(
      'radius_all',count(*),'radius_same_field',count(*) filter(where n.field=requested_field),
      'radius_pending',count(*) filter(where n.reason_code is not null),
      'radius_same_field_pending',count(*) filter(where n.field=requested_field and n.reason_code is not null),
      'by_field',(select coalesce(jsonb_object_agg(field,n),'{}'::jsonb) from fields)),
    'collection',jsonb_build_object('type','FeatureCollection',
      'features',coalesce(jsonb_agg(jsonb_build_object('type','Feature','id',n.id,
        'geometry',jsonb_build_object('type','Point','coordinates',
          jsonb_build_array(extensions.st_x(n.geom),extensions.st_y(n.geom))),
        'properties',jsonb_build_object('name',n.name,'field',n.field,
          'floor_label',n.floor_label,'floor_status',n.floor_status,
          'coordinate_verification_pending',n.reason_code is not null,
          'coordinate_review_reason',n.reason_code,'coordinate_review_version',n.review_version))
        order by n.id),'[]'::jsonb)))
    into invalid_display,payload from nearby n;
  if invalid_display then
    return response||jsonb_build_object('status','source_mismatch','reason','display_mismatch');
  end if;
  response:=response||payload||jsonb_build_object('status','ready','reason',null,
    'meta',jsonb_build_object('crs','EPSG:4326','source',source_meta,
      'source_revision',release.source_revision,'coordinate_provider','juso',
      'review_version',release.review_version,'unlocated_count_seoul',source_meta->'unlocated_count',
      'quality_inventory',jsonb_build_object('academy',academy_reviews,'school',school_reviews)));
  if (response#>>'{counts,radius_all}')::integer>5000 or octet_length(response::text)>1572864 then
    return jsonb_build_object('schema_version','1.0','status','too_dense','reason','response_budget_exceeded',
      'center',jsonb_build_array(lng,lat),'radius_m',radius_m,'field',requested_field,
      'collection',null,'counts',null,'meta',jsonb_build_object(
        'radius_count',(response#>>'{counts,radius_all}')::integer,
        'jsonb_bytes',octet_length(response::text),'raw_budget_bytes',1572864));
  end if;
  return response;
end;
$$;
revoke all on function public.academy_layer(double precision,double precision,integer,text,jsonb)
  from public,anon;
grant execute on function public.academy_layer(double precision,double precision,integer,text,jsonb)
  to authenticated;
