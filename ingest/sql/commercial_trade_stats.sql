-- normalized_trades retains raw records; equal public fields are not a transaction ID.
with eligible as (
    select * from normalized_trades where eligible
), grouped as (
    select legal_dong_code, trade_kind, 'all_floors' as aggregation_level,
        null::integer as floor,
        median(price_per_m2_won)::decimal(28,6) as median_price_per_m2,
        count(*)::integer as sample_count,
        count(*) filter(where floor_number is null)::integer as unknown_floor_count
    from eligible group by legal_dong_code,trade_kind
    union all
    select legal_dong_code, trade_kind, 'floor', floor_number::integer,
        median(price_per_m2_won)::decimal(28,6),count(*)::integer,0::integer
    from eligible where floor_number is not null
    group by legal_dong_code,trade_kind,floor_number
)
select *, 'building_area' as area_basis from grouped
order by legal_dong_code,trade_kind,aggregation_level,floor nulls first
