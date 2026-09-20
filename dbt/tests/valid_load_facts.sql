select f.logical_key
from {{ ref('fct_system_load_5min') }} as f
left join {{ source('raw', 'ingestion_runs') }} as r on f.state_run_id = r.run_id
left join {{ source('raw', 'ingestion_runs') }} as cr on f.first_run_id = cr.run_id
left join {{ source('raw', 'load_contents') }} as c on f.content_id = c.content_id
where r.status is null or r.status != 'SUCCEEDED'
    or cr.status is null or cr.status != 'SUCCEEDED'
    or c.content_id is null
    or f.logical_key is distinct from c.logical_key or f.content_hash is distinct from c.content_hash
    or f.source != 'CAISO'
    or f.logical_key_schema != 'observation-key/v1'
    or f.content_hash_schema != 'observation-content/v1'
    or f.interval_start_utc is null or f.interval_end_utc is null
    or timestamp_diff(f.interval_end_utc, f.interval_start_utc, second) != 300
    or mod(unix_seconds(f.interval_start_utc), 300) != 0
    or f.market_date != date(f.interval_start_utc, 'America/Los_Angeles')
    or f.state_known_at is null or f.first_seen_at is null
    or f.state_known_at is distinct from r.knowledge_at or f.first_seen_at is distinct from cr.knowledge_at
    or f.first_seen_at > f.state_known_at
    or f.load is null or f.load != c.load
    or f.unit != 'MW' or f.area != 'CAISO' or f.load < 0
    or f.source is distinct from c.source
    or f.product is distinct from c.product
    or f.source_dataset is distinct from c.source_dataset
    or f.market_date is distinct from c.market_date
    or f.interval_start_utc is distinct from c.interval_start_utc
    or f.interval_end_utc is distinct from c.interval_end_utc
    or f.unit is distinct from c.unit
    or f.area is distinct from c.area
