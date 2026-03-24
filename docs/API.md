# RadIMO API Reference

REST API endpoints for worker assignment and administration.

---

## Authentication

- **Operational assignment endpoints** are protected by basic access login when `access_protection_enabled` is true. Users authenticate via `/access-login`.
- **Admin endpoints** require an admin session when `admin_access_protection_enabled` is true. Users authenticate via `/login`.

When access protection is disabled, these endpoints are reachable without a session.

---

## Health & Readiness

### Liveness Probe

```http
GET /healthz
```

Public endpoint for process liveness. Returns HTTP `200` when the app is running.

**Example response:**
```json
{
  "status": "ok",
  "service": "RadIMO Cortex",
  "timestamp": "2026-02-10T12:34:56+01:00"
}
```

### Readiness Probe

```http
GET /readyz
```

Public endpoint for readiness. Returns HTTP:
- `200` when no operational check has status `ERROR`
- `503` when at least one operational check has status `ERROR`

`WARNING` checks do not fail readiness.

**Example response:**
```json
{
  "status": "ready",
  "service": "RadIMO Cortex",
  "timestamp": "2026-02-10T12:34:56+01:00",
  "summary": {
    "ok": 5,
    "warning": 1,
    "error": 0
  },
  "checks": [
    {
      "name": "Config File",
      "status": "OK",
      "detail": "APP_CONFIG is loaded and available"
    }
  ]
}
```

### Human Status Page

```http
GET /status
```

Public HTML page for manual inspection. It shows:
- current health/readiness badges
- readiness check list
- direct links to `/healthz` and `/readyz`

---

## Worker Assignment

### Assign Worker (with overflow)

```http
GET /api/{modality}/{skill}
```

Assigns a worker with overflow enabled unless the skill/modality is configured in `no_overflow`.
If `no_overflow` applies, routing becomes specialist-only but the request still uses normal weights.

**Parameters:**
| Name | Type | Description |
|------|------|-------------|
| modality | path | Modality slug from `config.yaml` (e.g., `ct`, `mr`, `xray`, `mammo`) |
| skill | path | Skill slug from `config.yaml` (e.g., `notfall`, `cvt`) |

**Example:**
```bash
curl http://localhost:5000/api/ct/cvt
```

**Response:**
```json
{
  "selected_person": "Dr. Anna Müller (AM)",
  "canonical_id": "AM",
  "source_modality": "ct",
  "skill_used": "cvt",
  "is_weighted": false
}
```

**Error response (no match):**
```json
{
  "error": "No available worker found"
}
```

---

### Assign Worker (strict, no overflow)

```http
GET /api/{modality}/{skill}/strict
```

Assigns a worker without overflow. Returns an error if no specialist is available.
This explicit strict path also uses strict weights.

---

## Master CSV Management (Admin)

### Master CSV Status

```http
GET /api/master-csv-status
```

Check if `master_medweb.csv` exists and get its metadata.

**Response (exists):**
```json
{
  "exists": true,
  "filename": "master_medweb.csv",
  "modified": "21.12.2025 20:30",
  "size": 12345
}
```

**Response (missing):**
```json
{
  "exists": false
}
```

---

### Upload Master CSV

```http
POST /upload-master-csv
```

Upload a new monthly medweb file.

Behavior:
- Replaces the stored `master_medweb.csv`
- Does **not** overwrite already staged `Prep Tomorrow` data by itself

**Parameters:**
- `file`: CSV file

---

### Hard Reload Today from Master

```http
POST /load-today-from-master
```

Rebuilds today's live schedule using the current date and Master CSV.

Behavior:
- applies a safe runtime config reload first when possible
- resets current live counters/flow state
- persists the rebuilt live backup used on restart
- does not touch staged tomorrow data

---

### Preload / Prep Tomorrow from Master

```http
POST /preload-from-master
```

Rebuilds staged next-day data from the current Master CSV and refreshes scheduled/staged files.

Behavior:
- accepts an optional selected `target_date`
- overwrites the staged plan for that selected target date
- this is the normal way to refresh `Prep Tomorrow` after a new CSV upload

---

## Info Texts (Admin)

### Update Modality Info Text

```http
POST /api/edit_info
```

Update the info text for a modality.

**Request:**
```json
{
  "modality": "ct",
  "info_text": "Line 1\nLine 2"
}
```

---

## Live Schedule (Admin)

### Get Live Data

```http
GET /api/live-schedule/data
```

### Update Live Row

```http
POST /api/live-schedule/update-row
```

### Add Live Worker

```http
POST /api/live-schedule/add-worker
```

### Delete Live Worker

```http
POST /api/live-schedule/delete-worker
```

### Add Live GAP (Split Shift)

```http
POST /api/live-schedule/add-gap
```

---

## Staged Schedule (Admin)

### Get Staged Data

```http
GET /api/prep-next-day/data
```

Returns staged schedules for all modalities plus `last_prepped_at` when available.

### Update Staged Row

```http
POST /api/prep-next-day/update-row
```

### Add Staged Worker

```http
POST /api/prep-next-day/add-worker
```

### Delete Staged Worker

```http
POST /api/prep-next-day/delete-worker
```

### Add Staged GAP

```http
POST /api/prep-next-day/add-gap
```

---

## Skill Matrix (Admin)

### Get Skill Matrix

```http
GET /api/admin/skill_roster
```

Returns the worker roster, skills list, and modalities list.

### Save Skill Matrix

```http
POST /api/admin/skill_roster
```

Persist roster changes to `worker_skill_roster.json`.

### Import New Workers

```http
POST /api/admin/skill_roster/import_new
```

Scan current schedules for workers missing from the roster and add them with default skills.

---

## Usage Statistics (Admin)

### Get Current Usage Statistics

```http
GET /api/usage-stats/current
```

### Export Usage Statistics

```http
POST /api/usage-stats/export
```

### Reset Usage Statistics

```http
POST /api/usage-stats/reset
```

### Get Usage CSV File Info

```http
GET /api/usage-stats/file
```

---

## Worker Load (Admin)

### Worker Load Data

```http
GET /api/worker-load/data
```

Returns the worker load monitoring payload for the dashboard.

---

## Error Responses

All endpoints may return error responses:

```json
{
  "error": "Error description",
  "success": false
}
```

HTTP status codes:
- `400` - Bad request (invalid parameters)
- `401` - Unauthorized (login required)
- `404` - No matching worker (assignment endpoints)
- `500` - Server error
