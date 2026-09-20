# CAISO fixtures

caiso_lmp.json and caiso_load.json are synthetic examples matching schemas
observed from gridstatus 0.36.0 on 2026-09-20 for historical 2026-08-01 requests.
They are not copied public CAISO observations. Each file contains two rows;
there are no credentials or bulk downloads.

LMP fixtures represent day-ahead hourly prices for NP15/SP15 in USD/MWh,
including a negative price and the returned energy/congestion/loss fields.
Load fixtures represent five-minute CAISO system demand in MW.
Time labels interval start under the inspected dependency's contract.

The JSON timestamps include explicit Pacific offsets. Test loading converts
them into pandas timestamps in US/Pacific to reproduce the actual returned
DataFrame shape. Tests derive missing values, malformed fields, revisions,
and DST examples in memory. UTC identity never relies on naive local labels.

See [source notes](../../docs/sources/caiso.md) and the
[domain/time contract](../../docs/contracts/observations.md) for provenance,
null rules, interval semantics and the fall-back load limitation.

All unit tests block socket connections and DNS resolution. Live smoke tests
are explicit CLI invocations outside pytest and CI.
