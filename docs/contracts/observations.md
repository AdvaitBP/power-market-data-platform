# Phase 1 observation, identity and time contracts

Records are frozen standard-library dataclasses. DataFrame column names remain
inside the CAISO adapter. Consumers receive built-in datetime and Decimal values,
not pandas objects. Record constructors enforce core interval/value invariants;
the source adapter additionally validates the returned schema and request scope.

## LMP grain and fields

**One normalized observation represents a CAISO day-ahead hourly LMP and its
exported components for one supported trading hub over one UTC hourly interval.**

The logical-key fields are exactly:

`source=CAISO`, `product=day_ahead_hourly_lmp`,
`market=DAY_AHEAD_HOURLY`, `location`, `interval_start_utc`,
`interval_end_utc`.

Intervals are [start, end), exactly one elapsed hour, aligned to the hour in UTC.
The content-hash fields are all logical-key fields plus
`unit=USD/MWh`, `lmp`, `energy`, `congestion`, and `loss`.

Location Type is validated as Trading Hub; the fixed classification and source
dataset PRC_LMP are descriptive, not additional grain dimensions. Only the three
documented trading hubs are accepted. The four numeric fields are required and
finite. Negative values are legitimate; there is no invented price cap,
clipping, or component-sum test. Missing components never become zero.

## Load grain and fields

**One normalized observation represents CAISO system demand from Today's Outlook
over one five-minute UTC interval.**

The logical-key fields are exactly:

`source=CAISO`, `product=system_load_5min`, `area=CAISO`,
`interval_start_utc`, `interval_end_utc`.

Intervals are [start, end), exactly five elapsed minutes, aligned to UTC
five-minute boundaries. The content-hash fields are all logical-key fields plus
`unit=MW` and `load`. The source dataset is todays_outlook_demand.

Load is required, finite and nonnegative because this product measures aggregate
system demand, not generation-adjusted net demand. Zero is allowed. This is a
power measurement; the adapter does not silently integrate it into MWh.

## Canonical identity serialization, version 1

Logical keys and content hashes are separate SHA-256 hex digests. Their inputs
are flat JSON objects containing the corresponding fields above plus:

- `schema=observation-key/v1` for a logical key;
- `schema=observation-content/v1` for a content hash.

All values are strings. JSON keys are sorted, separators are exactly comma and
colon without spaces, non-ASCII text is escaped, and the UTF-8 bytes have no
trailing newline. Datetimes use UTC, exactly six fractional digits, and Z
(e.g. 2026-08-01T07:00:00.000000Z). Sub-microsecond source values are rejected.

Numeric source values must actually be int, float or Decimal; booleans and
numeric-looking strings are rejected. Decimal(str(value)) preserves the numeric
representation exposed by gridstatus without adding binary-float artifacts.
Hash serialization uses fixed-point notation, removes trailing fractional zeros,
and normalizes any signed zero to "0". It is independent of Decimal context
precision. Precision already lost during source-library float parsing cannot be
recovered; exact original CSV bytes are not retained.

Neither Python hash(), row order, nor process hash randomization participates.
A price/load/component revision retains the logical key and changes the content
hash. A change only in retrieval time, URL, library version, or equivalent numeric
formatting does not create a content revision. An interval or hub change creates
a different logical identity. Exact repeats normalize to the same identities.

Changing grain or canonicalization requires an explicit version change and
migration decision. These primitives do not store versions or history. A→B→A
has the original content hash for A; Phase 2 still needs sighting/transition
history as required by ADR 002.

## UTC, Pacific time and DST

The installed source returns timezone-aware US/Pacific timestamps. The adapter
converts instants with astimezone(UTC), not tz_localize on an already-aware value.
Canonical fields use datetime.UTC. The CLI also renders Pacific boundaries with
explicit offsets using America/Los_Angeles; this is derived local context, not a
claim to preserve the raw CSV timestamp text.

The source Time field must equal Interval Start. Request dates are completed
Pacific calendar days; the exclusive end is the next local date, not start plus
24 UTC hours. LMP therefore permits 23- and 25-hour days without fabricating or
discarding intervals. No fixed 24-row completeness rule is imposed.

Naive datetimes are rejected, including ambiguous fall-back input. An explicit
offset or a correctly resolved timezone/fold identifies a unique instant.
Timezone-aware nonexistent wall times constructed during spring-forward are
rejected by round-trip validation. Winter/summer offsets are derived from the
IANA timezone database; tzdata is declared for Windows where a system database
may be absent.

During spring-forward, 01:00 PST to 03:00 PDT is one elapsed hour.
During fall-back, the two 01:00 starts with -07:00 and -08:00 identify different
UTC intervals and keys. LMP GMT source fields preserve this distinction.
The pinned load parser cannot establish it: **all load observations on a
25-hour Pacific day are rejected**, including direct normalizer input, pending
a verified source fix. There is no guessed fold or deduplication workaround.

## Provenance and failure behavior

Each returned record includes a provenance object with the completion time of
the library call in UTC, source endpoint, exact gridstatus version and method.
This retrieval time is not a source publication time or a committed warehouse
knowledge time. LMP provenance names the endpoint rather than claiming to retain
the exact generated request URL; its grain supplies hub/date context. No
unavailable revision IDs, source quality flags or publish timestamps are invented.

Missing/duplicate columns, malformed rows and unexpected return shapes raise
SchemaError. Missing/non-finite values, wrong labels, invalid intervals,
duplicate logical observations, or out-of-request rows raise ValidationError.
Unsupported hub/date requests raise UnsupportedRequestError before network I/O.
Source request failures/empty results raise UpstreamRequestError; dependency
KeyError/TypeError parsing failures are exposed as SchemaError with their cause.
CLI argument errors exit 2; project errors print to stderr and exit 1; success
prints bounded JSON to stdout and exits 0.

Extra upstream columns are tolerated but not silently incorporated into hashes.
No partial valid subset is returned if any received row fails. The dependency
can already drop rows/pivot duplicates before this boundary, so these checks do
not assert completeness or validate the original transport bytes.
