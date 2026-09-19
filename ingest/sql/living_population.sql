-- Age means use their own valid dates; missing/suppressed dates never become zeros.
-- sample_days counts dates with every SPOP dong fragment present and non-suppressed.
-- The source has only 0~9, so 0~4 and 5~9 cannot be reconstructed.
-- Combine sums and per-column valid-day counts; never average partial means.
with calendar_days as (
    select case when isodow(date) in (6,7) then 'weekend' else 'weekday' end as dow_type,
           count(*)::smallint as expected_days
    from calendar group by dow_type
), period as (
    select min(date) as period_start,max(date) as period_end from calendar
)
select cell_id,dow_type,hour,
       case when observed_days=expected_days and sample_days=expected_days
            then total_sum/nullif(total_days,0) else NULL end as total,
       NULL::double as age_0_4,
       NULL::double as age_5_9,
       age_10_14_sum/nullif(age_10_14_days,0) as age_10_14,
       age_15_19_sum/nullif(age_15_19_days,0) as age_15_19,
       age_20_29_sum/nullif(age_20_29_days,0) as age_20_29,
       age_30_39_sum/nullif(age_30_39_days,0) as age_30_39,
       age_40_49_sum/nullif(age_40_49_days,0) as age_40_49,
       age_50_59_sum/nullif(age_50_59_days,0) as age_50_59,
       age_60_plus_sum/nullif(age_60_plus_days,0) as age_60_plus,
       sample_days,period_start,period_end
from wide_summary join calendar_days using (dow_type) cross join period
