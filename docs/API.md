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

## Master CSV Management (Admin)

### Master CSV Status

```http
GET /api/master-csv-status
```

Check if `master_medweb.csv` exists and get its metadata.

**Response:**
```json
{
  "exists": true,
  "filename": "master_medweb.csv",
  "modified": "21.12.2025 20:30",
  "size": 12345
}
```

---

### Upload Master CSV

```http
POST /upload-master-csv
```

Upload a new monthly medweb file.

**Parameters:**
- `file`: CSV file

---

### Load Today from Master

```http
POST /load-today-from-master
```

Rebuilds today's live schedule using current date and Master CSV.

**Response:**
```json
{
  "success": true,
  "message": "Heute (21.12.2025) aus Master-CSV geladen",
  "modalities_loaded": ["ct", "mr", "xray"],
  "total_workers": 24
}
```

---

### Preload Tomorrow from Master

```http
POST /preload-from-master
```

Rebuilds tomorrow's staged schedule using Master CSV.

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

### Add Live GAP (Split Shift)

```http
POST /api/live-schedule/add-gap
```

**Request:**
```json
{
  "modality": "ct",
  "row_index": 5,
  "gap_type": "Board",
  "gap_start": "13:00",
  "gap_end": "14:00"
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
      "is_manual": false,
      "gap_id": "gap_AM_123456",
      "Normal": 1,
      "Notfall": 1,
      "Privat": 0,
      "Herz": 0,
      "Msk": 0,
      "Chest": 0
    }
  ],
  "mr": [...],
  "xray": [...],
  "last_prepped_at": "21.12.2025 14:00"
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

### Update Row
... (see above)

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

Get staged worker skill roster.

**Response:**
```json
{
  "success": true,
  "roster": {
    "AM": {
      "Normal_ct": 1,
      "Normal_mr": 1,
      "Normal_xray": 1,
      "Notfall_ct": 0,
      "Notfall_mr": 1,
      "Notfall_xray": 1,
      "Herz_ct": 1,
      "Herz_mr": 1
    }
  },
  "skills": ["Normal", "Notfall", "Privat", "Herz", "Msk", "Chest"],
  "modalities": ["ct", "mr", "xray"]
}
```

**Note:** Roster uses flat Skill×Modality combinations. Each key is `"skill_modality"` (e.g., `"Notfall_ct"`). Both `"skill_modality"` and `"modality_skill"` formats are accepted.

---

### Save Skill Matrix

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
      "Normal_ct": 1,
      "Normal_mr": 1,
      "Notfall_ct": 0,
      "Notfall_mr": 1,
      "Herz_ct": 1,
      "Herz_mr": 1
    }
  }
}
```

**Note:** Use flat Skill×Modality combinations. Each key is `"skill_modality"` format.

**Response:**
```json
{
  "success": true
}
```

---

### Activate Skill Matrix
*(Removed - Roster now saves directly)*

### Import New Workers

```http
POST /api/admin/skill_roster/import_new
```

Scan current schedules for workers missing from the roster and add them with default (-1) skills.

---

## Legacy Data Upload (DEPRECATED)

> [!WARNING]
> Use `/upload-master-csv` instead. This endpoint is kept for legacy compatibility but is dangerous as it overwrites the Master CSV.

### Upload Medweb CSV (for specific date)

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
