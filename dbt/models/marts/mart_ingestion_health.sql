-- This operational summary deliberately retains failures and unfinished runs.
select
    source,
    product,
    requested_date,
    requested_location,
    count(*) as run_count,
    sum(case when status = 'SUCCEEDED' then 1 else 0 end) as succeeded_run_count,
    sum(case when status = 'FAILED' then 1 else 0 end) as failed_run_count,
    sum(case when status = 'STARTED' then 1 else 0 end) as started_run_count,
    sum(case when status = 'COMMITTED' then 1 else 0 end) as unfinalized_run_count,
    max(case when status = 'SUCCEEDED' then knowledge_at end) as latest_successful_knowledge_at,
    sum(case when status = 'SUCCEEDED' then rows_accepted else 0 end) as successful_rows_accepted,
    sum(case when status = 'SUCCEEDED' then new_contents else 0 end) as successful_new_contents,
    sum(case when status = 'SUCCEEDED' then new_transitions else 0 end) as successful_new_transitions
from {{ ref('stg_ingestion_runs') }}
group by source, product, requested_date, requested_location
