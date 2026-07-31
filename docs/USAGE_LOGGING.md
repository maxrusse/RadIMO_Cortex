# Skill-Modality Usage Logging

The in-process usage logger counts successful assignments by the resolved
`(skill, modality)` pair. Both automatic assignment routes and successful
manual strict assignments reach the same finalization path and are recorded.
Failed assignments and candidate-list requests are not recorded.

## Storage and rollover

- Current counters live only in process memory.
- The CSV path is `logs/usage_stats/usage_stats.csv` relative to the app
  working directory. The logger creates its directory when it is imported.
- The file is wide format: `date` followed by every configured
  `skill_modality` column, with zero for unrecorded combinations.
- On the first successful recorded assignment after a calendar-date change,
  the prior in-memory counters are appended and then cleared.
- The scheduled check also runs after each successful assignment. Its
  implementation detects a new date; it does not use the scheduler's
  `daily_reset_time` value.

Manual export appends a snapshot without clearing counters. Therefore multiple
manual exports can produce multiple rows for the same date. Reset clears the
in-memory counters without writing a row. A process restart loses unexported
current-day data.

## Admin API

All endpoints below use the normal admin protection behavior.

| Method | Route | Result |
|---|---|---|
| GET | `/api/usage-stats/current` | Current date, totals, and nonzero in-memory counters. |
| POST | `/api/usage-stats/export` | Appends the current snapshot when counters exist; otherwise returns `success: false` with a message. |
| POST | `/api/usage-stats/reset` | Clears current counters. |
| GET | `/api/usage-stats/file` | CSV existence, size, dates, and date range. |

The export endpoint exposes the server-side path in its response; treat that
value as operational metadata and do not depend on an absolute location. CSV
columns are derived from the runtime skill and modality configuration, so a
configuration change can change future header expectations.

## Operational notes

The logger is protected by a threading lock for recording, exporting, resetting,
and reading counters. It does not use a database. If duplicate daily rows are
analysed, retain the last row for each date only when that matches the intended
snapshot semantics.
