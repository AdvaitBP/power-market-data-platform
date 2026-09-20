-- A content is eligible only after its original acceptance run succeeds.
select
    c.content_id,
    c.logical_key,
    c.content_hash,
    c.logical_key_schema,
    c.content_hash_schema,
    c.source,
    c.product,
    c.source_dataset,
    c.market_date,
    c.interval_start_utc,
    c.interval_end_utc,
    c.unit,
    c.retrieved_at_utc,
    c.source_url,
    c.source_method,
    c.library_version,
    c.first_run_id,
    c.first_seen_at,
    c.area,
    c.load
from {{ source('raw', 'load_contents') }} as c
inner join {{ ref('stg_ingestion_runs') }} as r on c.first_run_id = r.run_id
where r.status = 'SUCCEEDED'
