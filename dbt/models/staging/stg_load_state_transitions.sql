-- A COMMITTED but unfinalized transition is still ineligible.
select
    t.transition_id,
    t.run_id,
    t.logical_key,
    t.content_id,
    t.content_hash,
    t.logical_key_schema,
    t.content_hash_schema,
    t.market_date,
    t.interval_start_utc,
    t.ordinal,
    t.commit_sequence,
    t.retrieved_at_utc,
    t.known_at
from {{ source('raw', 'load_state_transitions') }} as t
inner join {{ ref('stg_ingestion_runs') }} as r on t.run_id = r.run_id
where r.status = 'SUCCEEDED'
