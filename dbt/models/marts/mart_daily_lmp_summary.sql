select
    source,
    market,
    location,
    market_date,
    count(*) as observation_count,
    avg(lmp) as average_lmp_usd_per_mwh,
    min(lmp) as minimum_lmp_usd_per_mwh,
    max(lmp) as maximum_lmp_usd_per_mwh,
    sum(case when lmp < 0 then 1 else 0 end) as negative_price_interval_count,
    timestamp_diff(
        timestamp(date_add(market_date, interval 1 day), 'America/Los_Angeles'),
        timestamp(market_date, 'America/Los_Angeles'),
        hour
    ) as expected_hour_count
from {{ ref('fct_hourly_lmp') }}
group by source, market, location, market_date
