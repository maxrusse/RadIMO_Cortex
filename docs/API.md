# RadIMO API Reference

This reference describes the routes registered in `routes.py`. Routes guarded by
`@access_required` require an access session only when
`access_protection_enabled` is enabled. Routes guarded by `@admin_required`
require an admin session only when `admin_access_protection_enabled` is enabled.
Health routes are public.

## Health

| Method | Route | Purpose |
|---|---|---|
| GET | `/healthz` | Liveness JSON; returns `200` while the process runs. |
| GET | `/readyz` | Readiness JSON; `200` unless an operational check is `ERROR`, then `503`. |
| GET | `/status` | Public human-readable health and readiness page. |

## Assignment

| Method | Route | Purpose |
|---|---|---|
| GET | `/api/{modality}/{role}` | Automatic assignment using normal weights. |
| GET | `/api/{modality}/{role}/strict` | Automatic specialist-only assignment using strict weights. |
| GET | `/api/{modality}/{role}/strict/candidates` | Candidates for a strict manual-selection button. |
| POST | `/api/{modality}/{role}/strict/manual` | Assign a strict candidate selected by the caller. |

`modality` and `role` must be configured route slugs. A role may also be the
slug of a configured special task. Normal assignment permits generalist
overflow unless the corresponding `no_overflow` entry or special-task setting
disables it. The explicit `/api/{modality}/{role}/strict` routes always disable overflow and use the
strict weight table.

Successful assignment responses contain `selected_person`, `canonical_id`,
`source_modality`, `skill_used`, `is_weighted`, `task_label`, and
`manual_selection`. Usage logging records the resolved `skill_used` and
`source_modality`, not necessarily the requested special-task slug.

For manual strict selection, send JSON with `candidate_key` (preferred) or an
unambiguous `worker_id`:

```json
{"candidate_key": "..."}
```

The candidates and manual routes return `404` when manual selection is not
enabled for that button. Manual assignment returns `400` when neither selector
is supplied and `409` when the requested candidate is no longer available.

## Administration

| Area | Routes |
|---|---|
| Login | `GET, POST /login`; `GET /logout`; `GET, POST /access-login`; `GET /access-logout` |
| Settings | `GET /admin/settings`; `POST /api/admin/config/general`; `POST /api/admin/runtime/reload` |
| Managed files | `GET /admin/files`; `GET /api/admin/files/manifest`; `GET /api/admin/files/download`; `POST /api/admin/files/upload`; `POST /api/admin/files/restore`; `POST /api/admin/files/reload` |
| Logs | `GET /admin/logs`; `GET /api/admin/logs/tail`; `GET /admin/logs/download` |
| Skills and weights | `GET, POST /api/admin/button_weights`; `GET, POST /api/admin/skill_roster`; `POST /api/admin/skill_roster/import_new`; `POST /api/admin/skill_roster/import_csv_worker` |

The general-settings endpoint accepts only `default_language`, `timezone`,
`worker_name_display_style`, `skill_roster_auto_import`,
`access_protection_enabled`, and `admin_access_protection_enabled`. It never
edits passwords or the secret key. It validates and backs up `config.yaml`,
then attempts a runtime reload. Changing modalities, skills, or `secret_key`
through the advanced YAML workflow requires an application restart.

`POST /api/admin/runtime/reload` requires `{"confirmation":"reload"}` and
returns `202` after scheduling a Gunicorn reload; it returns `409` when that
operation is unavailable.

For log downloads, `sources` accepts `gunicorn`, `selection`, `flow`, or
`all`; `scope` is `tail` or `full`; `lines` is an integer. Invalid source,
scope, or line values return `400`.

## Schedules and CSV

| Method | Route |
|---|---|
| GET | `/api/master-csv-status` |
| POST | `/upload-master-csv`, `/load-today-from-master`, `/preload-from-master` |
| GET | `/api/live-schedule/data`, `/api/prep-next-day/data` |
| POST | `/api/live-schedule/update-row`, `/api/live-schedule/apply-worker-plan`, `/api/live-schedule/create-worker-plan`, `/api/live-schedule/resolve-task-preview`, `/api/live-schedule/add-gap-batch` |
| POST | `/api/prep-next-day/update-row`, `/api/prep-next-day/apply-worker-plan`, `/api/prep-next-day/create-worker-plan`, `/api/prep-next-day/resolve-task-preview`, `/api/prep-next-day/add-gap-batch` |

Worker-plan endpoints treat the full worker plan as the mutation unit; an empty
`shifts` list removes that worker from the selected modalities. Staged-data
requests accept `target_date` in `YYYY-MM-DD` form; invalid dates return `400`.

## Monitoring and adjustments

| Method | Route |
|---|---|
| GET | `/api/usage-stats/current`, `/api/usage-stats/file` |
| POST | `/api/usage-stats/export`, `/api/usage-stats/reset` |
| GET | `/api/performance/data`, `/api/worker-load/data`, `/api/worker-load/daily-load`, `/api/worker-load/recent-distributions` |
| GET, POST | `/api/manual-adjustments` |

## Error convention

Errors are JSON with an `error` message. Some endpoints additionally return
`success: false`; consumers must not assume that field is universal. Assignment
exhaustion is semantic: it returns `404` with
`{"error":"No available worker found","code":"no_worker_available"}`.
Other common statuses are `400` for invalid input, `401` for required login,
`403` for failed confirmation, `409` for a stale strict candidate or unavailable
Gunicorn reload, `404` for absent resources/features, `500` for unexpected
failures, and `503` only for failed readiness.
