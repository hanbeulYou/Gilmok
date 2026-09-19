with point as (
  select extensions.st_setsrid(extensions.st_makepoint(%s,%s),4326)::extensions.geography as geom
), nearby as materialized (
  select s.id,s.type from public.transit_stops s,point p
  where extensions.st_dwithin(s.geom::extensions.geography,p.geom,%s)
), golden as (
  select n.id,count(b.hour) as hours,
         count(b.boarding) as boarding_hours,count(b.alighting) as alighting_hours,
         sum(b.boarding + b.alighting) as observed
  from nearby n left join public.transit_boardings b
    on b.stop_id=n.id and b.hour>=15 and b.hour<22
  where n.type='subway' group by n.id
)
select
  (select min(extensions.st_distance(s.geom::extensions.geography,p.geom))
   from public.transit_stops s,point p where s.type='subway'
   and extensions.st_dwithin(s.geom::extensions.geography,p.geom,2000)) as nearest_subway_m,
  (select count(*) from nearby where type='bus') as bus_stops,
  (select case when count(*) filter(where hours<>7 or boarding_hours<>7 or alighting_hours<>7)>0
               then null else coalesce(sum(observed),0) end from golden) as subway_boardings_golden,
  (select sum(observed) from golden) as observed_subway_boardings_golden,
  (select count(*) from golden where hours<>7 or boarding_hours<>7 or alighting_hours<>7)
    as subway_units_missing_golden;
