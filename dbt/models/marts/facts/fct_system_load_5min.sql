-- Phase 2 serializes finalization: later successful sequences cannot skip an
-- earlier unfinished data commit. No event-time predicate is safe here.
with candidate_states as (
    select *
    from {{ ref('int_load_revision_history') }}
    {% if is_incremental() %}
    where commit_sequence > (
        select coalesce(max(commit_sequence), 0) from {{ this }}
    )
    {% endif %}
),
ranked_states as (
    select
        *,
        row_number() over (
            partition by logical_key
            order by state_ordinal desc, commit_sequence desc, transition_id desc
        ) as state_rank
    from candidate_states
)
select
    content_id,
    logical_key,
    content_hash,
    logical_key_schema,
    content_hash_schema,
    source,
    product,
    source_dataset,
    market_date,
    interval_start_utc,
    interval_end_utc,
    unit,
    content_retrieved_at_utc,
    source_url,
    source_method,
    library_version,
    first_run_id,
    first_seen_at,
    area,
    load,
    transition_id,
    state_run_id,
    state_ordinal,
    commit_sequence,
    state_known_at,
    state_retrieved_at_utc
from ranked_states
where state_rank = 1
