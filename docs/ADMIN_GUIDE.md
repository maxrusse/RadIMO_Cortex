# RadIMO Admin Guide

Guide to the admin system for managing workers and schedules.

---

## Overview

RadIMO provides admin entry points for different operational needs:

| Page | URL | Effect | Use Case |
|------|-----|--------|----------|
| **Skill Matrix** | `/skill-roster` | Direct | Permanent skill management |
| **Schedule Edit (Today)** | `/prep-today` | Live | Same-day adjustments (Live Edit) |
| **Schedule Edit (Tomorrow)** | `/prep-tomorrow` | Staged | Daily schedule preparation |
| **Worker Load** | `/worker-load` | Monitor | Live load monitoring |
| **Weight Matrix** | `/button-weights` | Direct | Button weight configuration (incl. special tasks) |
| **Admin Panel** | `/upload` | Source + reset | Master CSV upload and day-reset actions |

Admin pages require login with the admin password from `config.yaml` when `admin_access_protection_enabled` is true.

---

## Workflow Separation

┌─────────────────────────────────────────────────────────────┐
│  SKILL MATRIX (Permanent)        /skill-roster              │
│  ├─ Multi-modality grid                                     │
│  ├─ Edit skill values (-1, 0, 1, w) + W modifier            │
│  └─ Save directly to roster JSON                            │
├─────────────────────────────────────────────────────────────┤
│  SCHEDULE EDIT                  /prep-today /prep-tomorrow  │
│  ├─ CHANGE TODAY:         Immediate live changes            │
│  │  └─ Adjust times, add/remove workers, split shifts       │
│  ├─ PREP TOMORROW:        Stage for next workday            │
│  │  └─ Prepare tomorrow's setup from Master CSV             │
│  └─ Both modes: Interactive GAP handling (Split Shift)      │
├─────────────────────────────────────────────────────────────┤
│  WEIGHT MATRIX (Load Balancing)  /button-weights            │
│  ├─ Skill×Modality weight grid (normal + strict modes)      │
│  ├─ Special task weights                                    │
│  └─ Save directly to button_weights.json                    │
└─────────────────────────────────────────────────────────────┘

---

## Skill Matrix (`/skill-roster`)

**Purpose:** Manage permanent worker skills across CT, MR, and X-ray.

**Key behavior:** Changes save directly to `worker_skill_roster.json` and take effect on the next reload/assignment.

### How It Works

1. Navigate to `/skill-roster` (or "Skill Matrix" in nav)
2. Select worker from the side list
3. Edit skill values in the grid:
   - **w** = Weighted/Training - 🔵 Blue
   - **0** = Passive (Helper/Fallback) - 🟡 Yellow
   - **-1** = Excluded (Never) - 🔴 Red
4. Set **W Modifier** for workers who may receive weighted (`w`) shift assignments:
   - `1.0` = normal workload (default)
   - `0.5` = 50% workload (trainee - gets half the assignments)
   - `0.75` = 75% workload (experienced but supervised)
5. Click **"Save"** to persist changes.
6. Use **"Import new workers"** to pull workers from current schedules who are missing from the roster.

**Important:** The roster is now only a baseline eligibility matrix:
- `w` = weighted/training baseline, only stays active when a shift assigns `1` or `w`
- `0` = worker may help as a passive/generalist
- `-1` = hard exclude
- `1` and most active day-state still come from shift assignments or live/prep edits

See [CONFIGURATION.md](CONFIGURATION.md#skill-value-hierarchy--overwrite-logic) for detailed overwrite rules.

### Example: Enable Passive Coverage
To allow "AM" to help on MHD work without making the roster an active-role source:
1. Select "AM"
2. Change MHD column in MR/CT to `0`
3. Click "Save"

---

## Schedule Edit (`/prep-today`, `/prep-tomorrow`)

**Purpose:** Edit schedules with two modes: "Edit Today" for immediate live changes, or "Prep Tomorrow" for planning.

**Key behavior:** Shared interface with modality tabs (CT/MR/XRAY).
- **Edit Today**: Immediate effect on live assignment pool.
- **Prep Tomorrow**: Stages changes for the next workday schedule.

### When to Use

**Edit Today:**
- Worker call-ins or sick leave adjustments.
- Urgent time shifts for today's workers.
- Add/Remove workers from the current live rotation.

**Prep Tomorrow:**
- Daily preparation based on the Master CSV.
- Adjusting Tomorrow's schedule before it goes live.

### Interface Components

Both modes share the same editing interface with modality-specific tables:

#### Data Loading
Each mode allows rebuilding from the master data:
- **Change Today** links to `HARD RELOAD TODAY` from the admin/upload page when a full day reset is really needed.
- **Prep Tomorrow** can rebuild the selected staged target date from the current `master_medweb.csv`.

#### Interactive Grid
- **Inline Edit**: Click any cell (Start, End, Skill, Modifier) to edit.
- **GAP Handling**: Use the "Add Gap" button to split a shift (e.g., for a 1-hour board meeting).
- **Advanced Mode**: Toggle to Add/Delete worker rows.

#### Filtering Controls

Both modes include smart filters:
- **Modality filter**: Show only specific modality (CT/MR/XRAY)
- **Skill filter**: Show only workers with specific skill active
- **Hide 0/-1 checkbox**: Hide workers without active `1/w` values for cleaner view

### Editable Fields

| Field | Format | Example |
|-------|--------|---------|
| Worker | Text | "Dr. Müller (AM)" |
| Start Time | HH:MM | "07:00" |
| End Time | HH:MM | "15:00" |
| Skills | -1, 0, 1, w | 1 (active) |
| Shift Load Modifier | 0.3-1.5 | 1.0 |

### Skill Value Colors

- 🟢 **Green (1)** = Active specialist (shift load modifier applied)
- 🟡 **Yellow (0)** = Passive/Fallback
- 🔴 **Red (-1)** = Excluded
- 🔵 **Blue (w)** = Weighted/learning (shift modifier + W modifier applied)

### Example Workflows

#### Fix Wrong Shift Time (Same Day)

**Scenario:** Worker "MS" has wrong start time TODAY.

1. Go to `/prep-today`
2. Confirm you're on the **Change Today** page (green header)
3. Use the modality filter (CT/MR/XRAY)
4. Find "MS" in the table
5. Click the start_time cell, change to the correct time
6. Click "Save Changes" → **Immediate effect**

#### Prepare Tomorrow's Schedule

**Scenario:** Plan tomorrow's coverage in advance.

1. Go to `/prep-tomorrow`
2. Confirm you're on the **Prep Tomorrow** page (yellow header)
3. Load/reload the selected target date from Master CSV if needed
4. Make adjustments as needed
5. Click "Save Changes" → Stored in the staged schedule for the next workday

---

## Admin Panel (`/upload`)

Central hub for Master CSV management and system health.

### Available Actions

| Action | Description |
|--------|-------------|
| **Master CSV Upload** | Replace the stored master medweb export |
| **MedSpace CSV Export** | Open the source export page in a new tab |
| **HARD RELOAD TODAY** | Rebuild today's live schedule from Master and reset counters |

### Workflow Strategy

1. **Upload Master CSV**: Once per month or whenever the master schedule changes.
2. **Daily Reset**: Automated at 07:30 CET, or manual only via `HARD RELOAD TODAY`.
3. **Daily Prep**: Use `Prep Tomorrow` in the evening for the next workday.
4. **Important:** Uploading a new Master CSV does **not** overwrite an already staged next day. Run `Prep Tomorrow` again for the target date if you want staged data refreshed from the new CSV.

---

## Logs (`/admin/logs`)

Use this page when you need browser access to runtime logs and do not have SSH access to the server.

### What It Provides

- **Tail archive**: current `gunicorn.log`, `selection.log`, and `flow_balance.log` with only the last N lines
- **Full archive**: the current log files plus their rotated backups (`.1`, `.2`, `.3`, ...)
- **Admin-only access**: protected by the existing admin login session

### Common Downloads

| Download | Example URL |
|----------|-------------|
| Current Gunicorn + RadIMO logs, tail | `/admin/logs/download?sources=gunicorn,selection&scope=tail&lines=5000` |
| All supported logs, full rotation set | `/admin/logs/download?sources=all&scope=full` |

### Notes

- `selection.log` is the main RadIMO application log.
- If `admin_access_protection_enabled` is enabled in `config.yaml`, users must log in via `/login` before they can open the logs page.

---

## Weight Matrix (`/button-weights`)

**Purpose:** Configure per-button weights for load balancing across skill×modality combinations and special tasks.

**Key behavior:** Changes save to `data/button_weights.json` (with automatic backup rotation) and take effect immediately.

### How It Works

1. Navigate to `/button-weights` (or "Weight Matrix" in admin nav)
2. Toggle between **Normal** and **Strict** modes using the mode selector
3. Edit weights in the matrix:
   - **Blank** = default (1.0)
   - **Higher values** (e.g., 1.5) = assignment counts more toward workload
   - **Lower values** (e.g., 0.5) = assignment counts less toward workload
4. Click **"Save"** to persist changes

### Skill×Modality Weights

The main matrix shows all skill×modality combinations. Invalid combinations (based on modality `valid_skills` config) are grayed out.

### Special Task Weights

Below the main matrix, special tasks are listed with their configuration:
- **Task**: Display label
- **Base Skill**: Which skill pool is used for assignments
- **Visible Modalities**: Which dashboards show this button
- **Skill Dashboards**: Which skill-view dashboards show this button
- **Overflow**: Whether generalists can be assigned
- **Weight**: Editable weight value (applies to all visible modalities)

### Example: Reduce CT Segmentation Workload Impact

To make CT Segmentation assignments count less toward worker load:
1. Go to `/button-weights`
2. Find "CT Segmentation" in the Special Tasks section
3. Set weight to `0.5` (assignments count as half)
4. Click "Save"

---

## Worker Load (`/worker-load`)

**Purpose:** Inspect current balance state without editing schedules.

Modes:
- **Simple**: Global worker weights plus aggregated `Per Modality` and `Per Skill` summary cards
- **Advanced**: Full worker matrix by modality × skill
- **Flow**: Cross-pool flow chart only

In `Simple`, the modality/skill cards show:
- weighted total as the main metric
- assignment count as supporting info
- number of active workers as supporting info

---

## Best Practices

### Daily Operations

1. **Morning:** Check auto-preload succeeded (view `/timetable`)
2. **During day:** Use assignment interface (`/` or `/by-skill`)
3. **Same-day adjustments:** Use `/prep-today` (immediate effect, counters preserved)
4. **End of day:** Review assignments, plan tomorrow via `/prep-tomorrow`
5. **Only if necessary:** Use `/upload` -> `HARD RELOAD TODAY` for a full rebuild of the current day

### Planning Rotations

1. Update `config.yaml` or `/skill-roster` with new skills
2. Save to staging
3. Test with `/prep-tomorrow` preview
4. Activate on rotation start day

### Same-Day Changes

**Option 1: Incremental Changes (Recommended)**
- Use `/prep-today`
- Preserves all assignment counters and history
- Immediate effect on schedule
- Use for: worker additions, time adjustments, skill corrections

**Option 2: Full Schedule Rebuild (Use with Caution)**
- Use Admin Panel → `HARD RELOAD TODAY`
- **WARNING:** Destroys ALL counters and assignment history
- Only use when schedule structure fundamentally changes
- Document reason and time of refresh

### Skill Management

| Change Type | Use This |
|-------------|----------|
| Permanent skill change | `config.yaml` → `worker_skill_roster` |
| Temporary/rotation change | `/skill-roster` |
| Same-day schedule edit | `/prep-today` |
| Tomorrow schedule prep | `/prep-tomorrow` |

---

## Troubleshooting

### Auto-preload didn't run

1. Check `selection.log` for errors
2. Verify master CSV exists in `uploads/`
3. Confirm the application was running at the configured daily reset time (currently 07:30)
4. Manual trigger: Use `Prep Tomorrow` to rebuild the selected staged date

### Need logs but no SSH access

1. Open `/admin/logs`
2. Download the tail archive first if you only need the latest messages
3. Use the full archive when you need rotated history
4. If the page redirects to login, authenticate with the admin password from `config.yaml`

### Worker missing from schedule

1. Check medweb CSV has correct date entry
2. Verify `medweb_mapping` rules match activity
3. Check `worker_skill_roster` for exclusions (-1)
4. Review `/prep-today` and `/prep-tomorrow` for manual deletions

### Skill changes not taking effect

1. Verify changes were saved (not just edited)
2. Skill Matrix changes take effect on next reload/assignment
3. Restart application if changed `config.yaml`

### Assignment not balanced

1. Check worker modifiers
2. Review the Weight Matrix (`/button-weights`) for button weight tweaks
3. Verify `min_assignments_per_skill` setting
4. Check imbalance threshold (default 30%)
