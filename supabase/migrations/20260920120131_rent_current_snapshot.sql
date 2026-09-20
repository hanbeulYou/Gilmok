-- Pin the latest loaded quarter before null/geography filters; never substitute history.
create or replace function public.rent_inputs(
  lng double precision, lat double precision, radius_m integer, floor integer default null,
  building_class text default null
) returns jsonb language plpgsql stable security invoker set search_path='' as $$
declare
  point extensions.geometry;
  dong_count integer;
  dong_code text;
  trade jsonb;
  by_type jsonb;
  survey jsonb;
  class_values jsonb;
  output jsonb;
  class_count integer;
begin
  if lng is null or lat is null or radius_m is null
    or not (lng between 124 and 132 and lat between 33 and 39 and radius_m between 1 and 5000)
    or (building_class is not null and length(btrim(building_class))=0) then
    raise exception 'Invalid rent query coordinates, radius or building class';
  end if;
  point := extensions.st_setsrid(extensions.st_makepoint(lng,lat),4326);
  select count(*),min(d.code8) into dong_count,dong_code
    from public.legal_dongs d where extensions.st_covers(d.geom,point);
  if dong_count <> 1 then dong_code := null; end if;

  select jsonb_agg(to_jsonb(t) order by t.sample_count desc,t.trade_kind)
    into by_type from public.commercial_trade_stats t
    where t.legal_dong_code=dong_code and
      ((rent_inputs.floor is null and t.aggregation_level='all_floors') or
       (rent_inputs.floor is not null and t.aggregation_level='floor'
          and t.floor=rent_inputs.floor));
  -- collection sorts ahead of general on ties, making the tie policy deterministic.
  trade := by_type->0;

  with latest_quarters as (
    select s.building_class,max(s.quarter) quarter from public.rent_survey s
    group by s.building_class
  ), candidates as (
    select r.*,a.level,
      count(*) over(partition by r.building_class,r.quarter,a.level) area_count
    from public.rent_survey r join latest_quarters q
      on q.building_class=r.building_class and q.quarter=r.quarter
    join public.rent_areas a using(area_code)
    where dong_code is not null and a.gu_code=left(dong_code,5)
      and a.mapping_verified and extensions.st_covers(a.geom,point)
      and (rent_inputs.building_class is null or r.building_class=rent_inputs.building_class)
      and r.rent_per_m2 is not null
      and a.valid_from <= make_date(left(r.quarter,4)::int,1+3*(right(r.quarter,1)::int-1),1)
      and a.valid_to >= (make_date(left(r.quarter,4)::int,
        1+3*(right(r.quarter,1)::int-1),1)+interval '3 months'-interval '1 day')::date
  ), latest as (
    select c.*,max(c.quarter) over(partition by c.building_class) newest from candidates c
  ), ranked as (
    select l.*,row_number() over(partition by l.building_class
      order by case l.level when 'district' then 0 else 1 end,l.area_code) rank
    from latest l where l.quarter=l.newest and l.area_count=1
  ) select jsonb_object_agg(ranked.building_class,jsonb_build_object(
    'survey_rent_per_m2',rent_per_m2,'survey_vacancy',vacancy_rate,
    'rent_level',level,'area_code',area_code,'quarter',quarter,
    'building_class',ranked.building_class,'source',source,'source_version',source_version,
    'rent_statbl_id',rent_statbl_id,'rent_cls_id',rent_cls_id,
    'vacancy_statbl_id',vacancy_statbl_id,'vacancy_cls_id',vacancy_cls_id))
    into class_values from ranked where rank=1;

  class_values := coalesce(class_values,'{}'::jsonb);
  select count(*) into class_count from jsonb_object_keys(class_values);
  -- No undocumented preference between office/medium/small/collective surveys.
  if class_count=1 then select value into survey from jsonb_each(class_values); end if;
  output := jsonb_build_object(
    'trade_median_per_m2',case when (trade->>'sample_count')::int >= 5
      then (trade->>'median_price_per_m2')::numeric else null end,
    'trade_building_type',trade->>'trade_kind',
    'trade_sample_count',(trade->>'sample_count')::int,
    'trade_by_building_type',coalesce(by_type,'[]'::jsonb),
    'survey_rent_per_m2',survey->'survey_rent_per_m2',
    'survey_vacancy',survey->'survey_vacancy',
    'rent_level',survey->>'rent_level',
    'survey_building_class',survey->>'building_class',
    'survey_by_building_class',class_values,
    'meta',jsonb_build_object('radius_m',radius_m,'floor',rent_inputs.floor,
      'legal_dong_code',dong_code,'spatial_scope','legal_dong_and_survey_area',
      'trade_missing_reason',case when dong_count=0 then 'outside_coverage'
        when dong_count>1 then 'ambiguous_legal_boundary'
        when trade is null then 'no_samples_for_requested_floor'
        when (trade->>'sample_count')::int < 5 then 'fewer_than_five_samples' else null end,
      'survey_missing_reason',case when dong_count<>1 then 'no_unique_legal_dong'
        when class_count=0 then 'no_verified_district_or_region_data'
        when class_count>1 then 'building_class_required' else null end,
      'estimated',false));
  return output;
end;
$$;
revoke all on function public.rent_inputs(double precision,double precision,integer,integer,text)
  from public;
grant execute on function public.rent_inputs(double precision,double precision,integer,integer,text)
  to anon,authenticated;
