# Notes

## Endpoint

```
GET /stations/{station_id}/starvation?date=YYYY-MM-DD
Authorization: Bearer metro-token
```

Returns `starved`, the supporting `empty_reading_count`, the threshold and UTC
window that were applied, `data_status` (`ok`, `no_data` or `out_of_service`),
the number of readings considered and how many were excluded. Errors: 401
(authentication), 404 (missing station or another operator's station; the two
responses are identical), 422 (input), 500 (invalid operator config) and 503
(database not seeded). Try it from `/docs` using **Authorize**.

## Assumptions that affect behaviour

- The peak window is `[date + peak_start, date + peak_end)` in UTC. If
  `peak_end` is earlier than `peak_start`, the window ends on the next day.
  Equal times are an invalid config.
- Readings are de-duplicated by UTC instant, and the row with the highest `id`
  wins. Station 104's duplicate 08:00 row is counted once (2 empty, not
  starved). Conflicting duplicates are logged.
- `docks_total == 0` means out of service. Those readings are excluded and
  reported. Station 103 is not starved, and its `data_status` is
  `out_of_service`.
- A window with no readings returns 200, `starved: false`,
  `data_status: no_data`. It does not return 404, because that would look the
  same as the tenant-isolation 404.
- Timestamps without an offset are treated as UTC, and timestamps with an
  offset are converted to UTC. Unparseable rows are skipped with a warning.
- `date` must be exactly `YYYY-MM-DD` and between 0001-01-02 and 9999-12-28.
  FastAPI's default date parsing also accepts Unix timestamps, for example
  `1694736000` becomes 2023-09-15, so the date is parsed explicitly.
  `station_id` must be between 1 and 2^63-1, which is SQLite's integer range.
- Bearer scheme matching is case-insensitive, and tokens are compared in
  constant time. Authentication is checked before input validation.
- Any reading inside the window counts, even off the 15-minute grid. Missing
  readings are not filled in.

## Incomplete functionality

- None against the brief. Left out on purpose: date ranges, several stations
  per request, token issuing or expiry, and local-time windows. The design
  keeps each one a local change. For example, `evaluate_starvation` is pure and
  works on one date at a time.

## Setup and run commands

- No changes to the supplied setup, dependencies or seed data. The commands in
  `README.md` work as given.
- The 8 supplied tests pass unchanged. `tests/conftest.py` only gains a
  `client` fixture.
- Design document: `Functional Design/station-health-functional-design.docx`.
