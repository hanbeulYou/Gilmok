-- Monthly totals are additive. A complete June-August mean is total / 92 days.
-- Missing months/hours are not interpreted as zero or averaged over fewer months.
with unpivoted as (
    select stop_id, month, measure, passengers from normalized
    unpivot include nulls (
        passengers for measure in (columns('^(boarding|alighting)_[0-9]+$'))
    )
), monthly as (
    select stop_id, month, measure,
           case when count(passengers) = count(*) then sum(passengers) end as passengers
    from unpivoted
    where stop_id is not null
    group by stop_id, month, measure
), complete as (
    select stop_id, measure, count(passengers) as sample_months,
           case when count(passengers) = 3 then sum(passengers) / $period_days end as mean
    from monthly group by stop_id, measure
)
select stop_id, cast(split_part(measure, '_', 2) as smallint) as hour,
       max(mean) filter (where measure like 'boarding_%') as boarding,
       max(mean) filter (where measure like 'alighting_%') as alighting,
       min(sample_months)::smallint as sample_months
from complete group by stop_id, hour order by stop_id, hour;
