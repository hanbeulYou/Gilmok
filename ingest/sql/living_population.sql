-- summary preserves sums, observed days and suppression counts across all raw files.
-- Never average monthly means or turn suppressed/missing observations into zero.
with calendar_days as (
    select case when isodow(date) in (6, 7) then 'weekend' else 'weekday' end as dow_type,
           count(*)::smallint as expected_days
    from calendar
    group by dow_type
)
select cell_id, dow_type, hour, age_band,
       case when observed_days = expected_days and suppressed_parts = 0
            then population_sum / expected_days else null end as avg_pop,
       observed_days, expected_days, suppressed_parts
from summary join calendar_days using (dow_type)
