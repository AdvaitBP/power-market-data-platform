select f.logical_key
from {{ ref('fct_hourly_lmp') }} as f
left join {{ source('raw', 'ingestion_runs') }} as r on f.state_run_id = r.run_id
left join {{ source('raw', 'ingestion_runs') }} as cr on f.first_run_id = cr.run_id
left join {{ source('raw', 'lmp_contents') }} as c on f.content_id = c.content_id
where r.status is null or r.status != 'SUCCEEDED'
    or cr.status is null or cr.status != 'SUCCEEDED'
    or c.content_id is null
    or f.logical_key is distinct from c.logical_key or f.content_hash is distinct from c.content_hash
    or f.source != 'CAISO'
    or f.logical_key_schema != 'observation-key/v1'
    or f.content_hash_schema != 'observation-content/v1'
    or f.interval_start_utc is null or f.interval_end_utc is null
    or timestamp_diff(f.interval_end_utc, f.interval_start_utc, second) != 3600
    or mod(unix_seconds(f.interval_start_utc), 3600) != 0
    or f.market_date != date(f.interval_start_utc, 'America/Los_Angeles')
    or f.state_known_at is null or f.first_seen_at is null
    or f.state_known_at is distinct from r.knowledge_at or f.first_seen_at is distinct from cr.knowledge_at
    or f.first_seen_at > f.state_known_at
    or f.lmp is null or f.lmp != c.lmp
    or f.unit != 'USD/MWh' or f.market != 'DAY_AHEAD_HOURLY'
    or f.location not in ('TH_NP15_GEN-APND', 'TH_SP15_GEN-APND', 'TH_ZP26_GEN-APND')
    or f.energy is null or f.congestion is null or f.loss is null
    or f.energy != c.energy or f.congestion != c.congestion or f.loss != c.loss
    or f.source is distinct from c.source
    or f.product is distinct from c.product
    or f.source_dataset is distinct from c.source_dataset
    or f.market_date is distinct from c.market_date
    or f.interval_start_utc is distinct from c.interval_start_utc
    or f.interval_end_utc is distinct from c.interval_end_utc
    or f.unit is distinct from c.unit
    or f.market is distinct from c.market
    or f.location is distinct from c.location
