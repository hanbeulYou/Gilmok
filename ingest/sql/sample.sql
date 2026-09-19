-- Synthetic smoke-test data only; this is not a public-data aggregation rule.
select code, count(value) as observed_count, sum(value) as total
from raw_data
group by code
order by code;
