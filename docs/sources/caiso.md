# CAISO source access (Phase 1)

Verified on 2026-09-20 with Python 3.12.14 and stable
[gridstatus 0.36.0](https://pypi.org/project/gridstatus/0.36.0/).
CAISO is the market-data source. The open-source gridstatus library performs
requests and its own parsing; it is not the market operator.

## Verified release API

The installed 0.36.0 release exports:

- `CAISO.get_lmp(date=..., end=..., market=Markets.DAY_AHEAD_HOURLY,
  locations=[hub])` for LMP.
- `CAISO.get_load(date=...)` for system load.

Its [release source](https://github.com/gridstatus/gridstatus/blob/v0.36.0/gridstatus/caiso/caiso.py)
was inspected before designing the contracts. The
[latest documentation](https://opensource.gridstatus.io/en/latest/autoapi/gridstatus/caiso/index.html)
lists `get_lmp_day_ahead_hourly` and deprecates generic `get_lmp`, but that
replacement is absent from the installed stable release. The release's generic
method is not marked deprecated and supports a specific hub. Do not replace it
with an unavailable API or silently fetch all nodes. Recheck on dependency upgrades.

## Day-ahead hourly prices

The adapter requests one completed Pacific calendar day at one of:

- TH_NP15_GEN-APND
- TH_SP15_GEN-APND
- TH_ZP26_GEN-APND

gridstatus requests CAISO OASIS SingleZip, query PRC_LMP, version 12, market DAM,
with a node filter. It converts the OASIS GMT interval fields to aware US/Pacific
timestamps and pivots component rows. Returned columns observed in the live call:

`Time`, `Interval Start`, `Interval End`, `Market`, `Location`,
`Location Type`, `LMP`, `Energy`, `Congestion`, `Loss`.

Time duplicates Interval Start. Market is DAY_AHEAD_HOURLY and these locations
are classified as Trading Hub. Prices and components are USD/MWh.
[CAISO's price guide](https://www.caiso.com/todays-outlook/prices) identifies OASIS
as the source for official price reports.

The installed method does not expose GHG or source revision/publication IDs in
this returned schema. Do not manufacture them. Observed total prices did not
equal the sum of the three exported components; no component-sum invariant is
enforced. The dependency pivots duplicate component rows using the first value,
so this adapter cannot recover information already discarded by that operation.

## System load

gridstatus reads the historical Today's Outlook demand CSV at
`https://www.caiso.com/outlook/history/YYYYMMDD/demand.csv` and selects
Current demand as Load. The returned columns are `Time`, `Interval Start`,
`Interval End`, and `Load`; timestamps are aware US/Pacific.

[CAISO describes demand as a five-minute average in MW](https://www.caiso.com/todays-outlook).
This is system demand, not net demand, a forecast, or an energy total.
The published trend excludes dispatchable pump loads and charging battery
storage. The pinned library treats Time as interval start and creates an end
five minutes later. This is the interval convention preserved here; it is not
an independent verification of settlement-meter interval labeling.

The dependency drops missing Load rows before returning them. Consequently,
validated returned rows do not establish full-day completeness. Its local-time
parser also chooses the first offset for ambiguous fall-back labels. The adapter
rejects the entire 25-hour Pacific day before fetching, and rejects such rows
during normalization. It does not claim to repair this upstream ambiguity.

## Access, usage and limits

[OASIS](https://www.caiso.com/systems-applications/portals-applications/open-access-same-time-information-system-oasis)
provides market reports; the
[CAISO FAQ](https://www.caiso.com/documents/oasis-frequently-asked-questions.pdf)
distinguishes those market outputs from Today's Outlook telemetry summaries.
They must not be treated as interchangeable measures.

The library uses a BSD-style three-clause software license. That license does
not grant blanket rights to underlying CAISO data. CAISO publishes separate
[website/API terms](https://www.caiso.com/privacy-terms-of-use), including limits
on excessive use and a conditional API license. Today's Outlook is informational,
subject to change, and not intended for billing or operational planning. Review
the current terms before redistributing source data. Committed fixtures here
are synthetic; fetched records are not redistributed.

Requests need no credentials. The adapter adds no retries and makes one bounded
day/product request. gridstatus retains its own request behavior (including OASIS
HTTP-status retries and a default five-second sleep). Its OASIS URL uses HTTP and
does not set a request timeout in this release; load uses HTTPS. Phase 1 does not
add a transport replacement or claim bounded wall-clock completion.

The CLI's --limit restricts printing, not the fetched day. No bulk dates, all-node
requests, or live requests run in CI. Source history may be missing/unavailable;
request errors and empty results remain visible. The OASIS portal advertises a
separate downloader for older archives; this adapter does not use it.

## Observed smoke test

On 2026-09-20, both installed CLI commands succeeded for 2026-08-01:

- NP15 day-ahead LMP: 24 normalized hourly observations.
- System load: 288 normalized five-minute observations.

Two records from each were inspected for UTC boundaries, units, source fields,
64-character logical keys/content hashes, and retrieval metadata. Output was
printed without writing downloaded observations to disk. This is evidence for
these requests, not a guarantee of coverage on other days or all hubs.

The [observation contract](../contracts/observations.md) defines validation,
identity serialization, and time handling.
