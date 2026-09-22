-- Compare complete projected rows in both directions, plus explicit grain/units.
with missing_or_changed as (
    select source, market, unit, market_date, location, interval_start_utc, interval_end_utc, lmp, logical_key, content_id, content_hash, logical_key_schema, content_hash_schema, transition_id, state_run_id, state_ordinal, commit_sequence, first_seen_at, state_known_at from {{ ref('fct_hourly_lmp') }}
    except distinct
    select source, market, unit, market_date, location, interval_start_utc, interval_end_utc, lmp, logical_key, content_id, content_hash, logical_key_schema, content_hash_schema, transition_id, state_run_id, state_ordinal, commit_sequence, first_seen_at, state_known_at from {{ ref('mart_battery_optimization_inputs') }}
), extra_or_changed as (
    select source, market, unit, market_date, location, interval_start_utc, interval_end_utc, lmp, logical_key, content_id, content_hash, logical_key_schema, content_hash_schema, transition_id, state_run_id, state_ordinal, commit_sequence, first_seen_at, state_known_at from {{ ref('mart_battery_optimization_inputs') }}
    except distinct
    select source, market, unit, market_date, location, interval_start_utc, interval_end_utc, lmp, logical_key, content_id, content_hash, logical_key_schema, content_hash_schema, transition_id, state_run_id, state_ordinal, commit_sequence, first_seen_at, state_known_at from {{ ref('fct_hourly_lmp') }}
), invalid as (
    select logical_key
    from {{ ref('mart_battery_optimization_inputs') }}
    where source is null
        or market is null
        or unit is null
        or market_date is null
        or location is null
        or interval_start_utc is null
        or interval_end_utc is null
        or lmp is null
        or logical_key is null
        or content_id is null
        or content_hash is null
        or logical_key_schema is null
        or content_hash_schema is null
        or transition_id is null
        or state_run_id is null
        or state_ordinal is null
        or commit_sequence is null
        or first_seen_at is null
        or state_known_at is null
        or source != 'CAISO' or market != 'DAY_AHEAD_HOURLY' or unit != 'USD/MWh'
        or timestamp_diff(interval_end_utc, interval_start_utc, second) != 3600
        or interval_start_utc != timestamp_trunc(interval_start_utc, hour)
        or market_date != date(interval_start_utc, 'America/Los_Angeles')
        or logical_key_schema != 'observation-key/v1'
        or content_hash_schema != 'observation-content/v1'
), duplicates as (
    select location, interval_start_utc
    from {{ ref('mart_battery_optimization_inputs') }}
    group by location, interval_start_utc having count(*) != 1
)
select 'missing_or_changed' as violation from missing_or_changed
union all select 'extra_or_changed' from extra_or_changed
union all select 'invalid' from invalid
union all select 'duplicate_grain' from duplicates
