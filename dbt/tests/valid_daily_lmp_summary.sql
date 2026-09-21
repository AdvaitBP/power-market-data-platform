-- Counts describe observed intervals; they do not establish source completeness.
select market_date, location
from {{ ref('mart_daily_lmp_summary') }}
where observation_count < 1 or observation_count > expected_hour_count
    or expected_hour_count not in (23, 24, 25)
    or negative_price_interval_count < 0
    or negative_price_interval_count > observation_count
    or average_lmp_usd_per_mwh < minimum_lmp_usd_per_mwh
    or average_lmp_usd_per_mwh > maximum_lmp_usd_per_mwh
