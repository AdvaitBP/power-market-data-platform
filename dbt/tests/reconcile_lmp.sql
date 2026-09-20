-- Compare against raw transitions independently of the staging eligibility filter.
with eligible as (
    select t.*
    from {{ source('raw', 'lmp_state_transitions') }} as t
    inner join {{ source('raw', 'ingestion_runs') }} as r on t.run_id = r.run_id
    where r.status = 'SUCCEEDED'
),
ranked as (
    select *,
        row_number() over (
            partition by logical_key
            order by ordinal desc, commit_sequence desc, transition_id desc
        ) as state_rank
    from eligible
),
expected_current as (
    select * from ranked where state_rank = 1
),
history_errors as (
    select coalesce(e.transition_id, h.transition_id) as offending_id
    from eligible as e
    full outer join {{ ref('int_lmp_revision_history') }} as h
        on e.transition_id = h.transition_id
    where e.transition_id is null or h.transition_id is null
        or e.logical_key is distinct from h.logical_key or e.content_id is distinct from h.content_id
        or e.content_hash is distinct from h.content_hash or e.ordinal is distinct from h.state_ordinal
        or e.commit_sequence is distinct from h.commit_sequence or e.known_at is distinct from h.state_known_at
),
current_errors as (
    select coalesce(e.logical_key, f.logical_key) as offending_id
    from expected_current as e
    full outer join {{ ref('fct_hourly_lmp') }} as f on e.logical_key = f.logical_key
    where e.logical_key is null or f.logical_key is null
        or e.transition_id is distinct from f.transition_id or e.content_id is distinct from f.content_id
        or e.content_hash is distinct from f.content_hash or e.ordinal is distinct from f.state_ordinal
        or e.commit_sequence is distinct from f.commit_sequence or e.known_at is distinct from f.state_known_at
)
select 'history' as contract, offending_id from history_errors
union all
select 'current' as contract, offending_id from current_errors
