# RadIMO API Reference

REST API endpoints for worker assignment and administration.

---

## Authentication

Admin endpoints require session authentication via `/login`.

---

## Worker Assignment

### Assign Worker (with fallback)

```http
GET /api/{modality}/{skill}
```

Assigns a worker with automatic fallback if no direct match available.

**Parameters:**
| Name | Type | Description |
|------|------|-------------|
| modality | path | `ct`, `mr`, or `xray` |
| skill | path | `normal`, `notfall`, `privat`, `herz`, `msk`, `chest` |

**Example:**
```bash
curl http://localhost:5000/api/ct/herz
```

**Response:**
```json
{
  "Assigned Person": "Dr. Anna Müller (AM)",
  "Draw Time": "14:23:45",
  "Modality": "ct",
  "Requested Skill": "Herz",
  "Used Skill": "Herz",
  "Fallback Used": false
}
```

**Fallback response:**
```json
{
  "Assigned Person": "Dr. Max Schmidt (MS)",
  "Draw Time": "14:24:12",
  "Modality": "ct",
  "Requested Skill": "Herz",
  "Used Skill": "Notfall",
  "Fallback Used": true,
  "Fallback Reason": "No active Herz workers available"
}
```

---

### Assign Worker (strict, no fallback)

```http
GET /api/{modality}/{skill}/strict
```

Assigns a worker without fallback. Returns error if no direct match.

**Example:**
```bash
curl http://localhost:5000/api/ct/herz/strict
```

**Error response (no match):**
```json
{
  "error": "No available worker for Herz in ct",
  "Fallback Used": false
}
```

---

## Statistics

### Quick Reload (modality view)

```http
GET /api/quick_reload?modality={modality}
```

Get live statistics for modality-based view.

**Example:**
```bash
curl http://localhost:5000/api/quick_reload?modality=ct
```

**Response:**
```json
{
  "available_buttons": {
    "normal": true,
    "notfall": true,
    "herz": true,
    "privat": false
  },
  "operational_checks": {
    "workers_loaded": true,
    "config_valid": true
  }
}
```

---

### Quick Reload (skill view)

```http
GET /api/quick_reload?skill={skill}
```

Get live statistics for skill-based view.

**Example:**
```bash
curl http://localhost:5000/api/quick_reload?skill=herz
```

**Response:**
```json
{
  "available_modalities": {
    "ct": true,
    "mr": true,
    "xray": false
  },
  "operational_checks": {...}
}
```

---

## Prep Next Day (Admin)

### Get Prep Data

```http
GET /api/prep-next-day/data
```

Get staged working_hours_df for all modalities.

**Response:**
```json
{
  "ct": [
    {
      "row_index": 0,
      "PPL": "Dr. Müller (AM)",
      "start_time": "07:00",
      "end_time": "15:00",
      "Modifier": 1.0,
      "Normal": 1,
      "Notfall": 1,
      "Privat": 0,
      "Herz": 0,
      "Msk": 0,
      "Chest": 0
    }
  ],
  "mr": [...],
  "xray": [...]
}
```

---

### Update Row

```http
POST /api/prep-next-day/update-row
Content-Type: application/json
```

Update a single worker row in staged data.

**Request:**
```json
{
  "modality": "ct",
  "row_index": 5,
  "updates": {
    "start_time": "08:00",
    "end_time": "16:00",
    "Normal": 1,
    "Notfall": 0
  }
}
```

**Response:**
```json
{
  "success": true
}
```

---

### Add Worker

```http
POST /api/prep-next-day/add-worker
Content-Type: application/json
```

Add new worker to staged data.

**Request:**
```json
{
  "modality": "mr",
  "worker_data": {
    "PPL": "Neuer Worker (NW)",
    "start_time": "07:00",
    "end_time": "15:00",
    "Normal": 1,
    "Notfall": 1,
    "Privat": 0,
    "Herz": 0,
    "Msk": 0,
    "Chest": 0,
    "Modifier": 1.0
  }
}
```

**Response:**
```json
{
  "success": true,
  "row_index": 12
}
```

---

### Delete Worker

```http
POST /api/prep-next-day/delete-worker
Content-Type: application/json
```

Delete worker from staged data.

**Request:**
```json
{
  "modality": "xray",
  "row_index": 3
}
```

**Response:**
```json
{
  "success": true
}
```

---

### Activate Staged Schedule

```http
POST /api/prep-next-day/activate
Content-Type: application/json
```

Copy staged data to live and reset counters.

**Request:**
```json
{
  "modalities": ["ct", "mr", "xray"]
}
```

**Response:**
```json
{
  "success": true,
  "activated_modalities": ["ct", "mr", "xray"],
  "total_workers": 45,
  "warning": "All assignment counters have been reset"
}
```

---

## Skill Roster (Admin)

### Get Skill Roster

```http
GET /api/admin/skill_roster
```

Get staged worker skill roster.

**Response:**
```json
{
  "success": true,
  "roster": {
    "AM": {
      "default": {"Normal": 1, "Notfall": 1, "Herz": 1, ...},
      "ct": {"Notfall": 0}
    }
  },
  "skills": ["Normal", "Notfall", "Privat", "Herz", "Msk", "Chest"],
  "modalities": ["ct", "mr", "xray"],
  "is_staged": true
}
```

---

### Save Skill Roster

```http
POST /api/admin/skill_roster
Content-Type: application/json
```

Save roster changes to staging.

**Request:**
```json
{
  "roster": {
    "AM": {
      "default": {"Normal": 1, "Notfall": 1, "Herz": 1}
    }
  }
}
```

**Response:**
```json
{
  "success": true,
  "message": "Roster changes staged (15 workers) - Use \"Activate\" to apply"
}
```

---

### Activate Skill Roster

```http
POST /api/admin/skill_roster/activate
```

Copy staged roster to active.

**Response:**
```json
{
  "success": true,
  "message": "Roster activated successfully (15 workers)"
}
```

---

## Live Edit (Admin)

### Get Workers

```http
GET /api/live_edit/workers?modality={modality}
```

Get current workers for live editing.

**Response:**
```json
{
  "success": true,
  "workers": [
    {
      "index": 0,
      "PPL": "Dr. Müller (AM)",
      "start_time": "07:00:00",
      "end_time": "15:00:00",
      "shift_duration": 8.0,
      "Modifier": 1.0,
      "Normal": 1,
      "Notfall": 1,
      ...
    }
  ],
  "modality": "ct"
}
```

---

### Edit Entry (Live)

```http
POST /edit
Content-Type: application/x-www-form-urlencoded
```

Edit worker entry with immediate effect.

**Parameters:**
| Name | Type | Description |
|------|------|-------------|
| index | form | Row index (omit for new entry) |
| person | form | Worker name |
| time | form | Shift time range (e.g., "07:00-15:00") |
| modifier | form | Worker modifier |
| normal | form | Normal skill value |
| notfall | form | Notfall skill value |
| ... | form | Other skills |
| modality | form | Target modality |

**Response:**
```json
{
  "success": true,
  "message": "Entry updated successfully"
}
```

---

### Delete Entry (Live)

```http
POST /delete
Content-Type: application/x-www-form-urlencoded
```

Delete worker entry (sets time to 00:00-00:00).

**Parameters:**
| Name | Type | Description |
|------|------|-------------|
| index | form | Row index |
| modality | form | Target modality |

**Response:**
```json
{
  "success": true,
  "message": "Entry deleted successfully"
}
```

---

## CSV Upload (Admin)

### Upload Medweb CSV

```http
POST /upload
Content-Type: multipart/form-data
```

Upload medweb CSV for specific date.

**Parameters:**
| Name | Type | Description |
|------|------|-------------|
| file | file | Medweb CSV file |
| target_date | form | Date (YYYY-MM-DD) |

---

### Preload Next Workday

```http
POST /preload-next-day
Content-Type: multipart/form-data
```

Preload next workday (Friday → Monday logic).

**Parameters:**
| Name | Type | Description |
|------|------|-------------|
| file | file | Medweb CSV file |

---

### Force Refresh Today

```http
POST /force-refresh-today
Content-Type: multipart/form-data
```

Emergency same-day reload. Destroys all counters.

**Parameters:**
| Name | Type | Description |
|------|------|-------------|
| file | file | Medweb CSV file |

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
- `500` - Server error
