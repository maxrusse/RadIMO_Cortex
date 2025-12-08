# RadIMO Admin Guide

Guide to the three-page admin system for managing workers and schedules.

---

## Overview

RadIMO provides three distinct admin interfaces for different operational needs:

| Page | URL | Effect | Use Case |
|------|-----|--------|----------|
| **Skill Roster** | `/skill_roster` | Staged | Long-term planning, rotations |
| **Prep Next Day** | `/prep-next-day` | Tomorrow only | Daily schedule preparation |
| **Live Edit** | `/admin/live-edit` | Immediate | Emergency same-day changes |

All admin pages require login with the admin password from `config.yaml`.

---

## Workflow Separation

```
┌─────────────────────────────────────────────────────────────┐
│  PLANNING (Future)              Skill Roster                │
│  ├─ Staged changes              (Planning Mode)             │
│  ├─ Review before apply                                     │
│  └─ Activate when ready                                     │
├─────────────────────────────────────────────────────────────┤
│  PREP (Tomorrow)                Prep Next Day               │
│  ├─ Upload CSV for next day                                 │
│  ├─ Preview and adjust                                      │
│  └─ No effect on current day                                │
├─────────────────────────────────────────────────────────────┤
│  OPERATIONAL (Now)              Live Edit                   │
│  ├─ Immediate effect            (DANGER ZONE)               │
│  ├─ Emergency changes only                                  │
│  └─ Careful: impacts ongoing assignments                    │
└─────────────────────────────────────────────────────────────┘
```

---

## 1. Skill Roster (`/skill_roster`)

**Purpose:** Plan worker skill changes for rotations and long-term scheduling.

**Key behavior:** Changes are STAGED - no immediate effect on assignments.

### When to Use

- Weekly rotation planning
- Training certifications
- Scheduled skill changes
- Long-term worker configuration

### How It Works

1. Navigate to `/skill_roster`
2. Find worker in table by abbreviation
3. Edit skill values:
   - **1** = Active (primary + fallback)
   - **0** = Passive (fallback only)
   - **-1** = Excluded (never)
4. Click **"Save to Staging"** → saves to `worker_skill_overrides_staged.json`
5. When ready: Click **"Activate Changes"** → copies staged → active

### Example: Add MSK Rotation

**Scenario:** Worker "AM" starts MSK rotation next week.

1. Go to `/skill_roster`
2. Find "AM" in the table
3. Change MSK from `0` → `1`
4. Click "Save to Staging" → no immediate effect
5. On rotation start day: Click "Activate Changes" → now active

### Files

- **Staged:** `worker_skill_overrides_staged.json`
- **Active:** `worker_skill_overrides.json`

---

## 2. Prep Next Day (`/prep-next-day`)

**Purpose:** Prepare and preview tomorrow's worker schedule.

**Key behavior:** Changes affect tomorrow's date only - no impact on today.

### When to Use

- Daily schedule preparation
- Correcting mapping edge cases
- Adjusting times before auto-preload
- Testing schedule changes safely

### Two Editing Modes

#### Simple Mode (Default)

**For:** Quick inline edits

- Click any cell to edit
- Edited cells highlight until saved
- Edit: worker names, times, skills, modifiers

#### Advanced Mode

**For:** Structural changes

- Toggle with "Advanced" button
- Add new worker rows
- Delete worker rows
- Bulk skill operations (set all workers to skill value)
- All Simple Mode features available

### Editable Fields

| Field | Format | Example |
|-------|--------|---------|
| Worker | Text | "Dr. Müller (AM)" |
| Start Time | HH:MM | "07:00" |
| End Time | HH:MM | "15:00" |
| Skills | -1, 0, 1 | 1 (active) |
| Modifier | Decimal | 1.0 |

### Skill Value Colors

- 🟢 **Green (1)** = Active
- 🟡 **Yellow (0)** = Passive/Fallback
- 🔴 **Red (-1)** = Excluded

### Example: Fix Wrong Shift Time

**Scenario:** Worker "MS" has wrong start time for tomorrow.

1. Go to `/prep-next-day`
2. Select modality tab (CT/MR/XRAY)
3. Find "MS" in table
4. Click start_time cell, change to correct time
5. Click "Save All Changes"

### Activation

Changes are applied when:
- Auto-preload runs at 7:30 AM
- Manual "Activate" button clicked
- Today becomes tomorrow (next day logic)

---

## 3. Live Edit (`/admin/live-edit`)

**Purpose:** Make immediate changes to current day's assignments.

**Key behavior:** Changes take effect IMMEDIATELY.

### When to Use

- Emergency substitutions
- Last-minute schedule changes
- Same-day corrections
- Urgent worker additions/removals

### Features

- Modality tabs (CT/MR/XRAY)
- Real-time worker list with current assignments
- Edit worker hours, names, skills, modifiers
- Delete worker entries
- Add new workers

### Warning

Changes are **INSTANT** and affect:
- Current assignment calculations
- Workload ratios
- Availability for new assignments

Use with caution!

### Example: Emergency Sick Call

**Scenario:** Worker "AM" calls in sick at 9 AM.

1. Go to `/admin/live-edit`
2. Select modality tab where "AM" is assigned
3. Find "AM" in table
4. Click Delete or set time to "00:00-00:00"
5. Confirm → Worker immediately removed from pool

### Example: Add Replacement Worker

1. Go to `/admin/live-edit`
2. Click "Add New Worker" button
3. Fill in details: name, time, skills
4. Submit → Worker immediately available for assignment

---

## Admin Panel (`/upload`)

Central hub for system management.

### Available Actions

| Action | Description |
|--------|-------------|
| **Medweb CSV Upload** | Upload schedule for specific date |
| **Preload Next Workday** | Manual trigger of auto-preload |
| **Force Refresh Today** | Emergency same-day reload (destroys counters) |

### CSV Upload Flow

1. Click "Medweb CSV Upload"
2. Select CSV file
3. Choose target date
4. Upload → System parses and builds schedule

### Auto-Preload

- Runs daily at **07:30 CET**
- Uses last uploaded CSV as master
- Applies next workday logic (Friday → Monday)

---

## Best Practices

### Daily Operations

1. **Morning:** Check auto-preload succeeded (view `/timetable`)
2. **During day:** Use assignment interface (`/` or `/by-skill`)
3. **End of day:** Review assignments, plan tomorrow via `/prep-next-day`

### Planning Rotations

1. Update `config.yaml` or `/skill_roster` with new skills
2. Save to staging
3. Test with `/prep-next-day` preview
4. Activate on rotation start day

### Emergency Changes

1. Prefer `/admin/live-edit` for targeted fixes
2. Use "Force Refresh Today" only as last resort
3. Document emergency changes for tracking

### Skill Management

| Change Type | Use This |
|-------------|----------|
| Permanent skill change | `config.yaml` → `worker_skill_roster` |
| Temporary/rotation change | `/skill_roster` staging |
| One-day override | `/prep-next-day` |
| Emergency same-day | `/admin/live-edit` |

---

## Troubleshooting

### Auto-preload didn't run

1. Check `selection.log` for errors
2. Verify master CSV exists in `uploads/`
3. Confirm application was running at 07:30 CET
4. Manual trigger: Use admin panel "Preload Next Workday"

### Worker missing from schedule

1. Check medweb CSV has correct date entry
2. Verify `medweb_mapping` rules match activity
3. Check `worker_skill_roster` for exclusions (-1)
4. Review `/prep-next-day` for manual deletions

### Skill changes not taking effect

1. Verify changes were saved (not just edited)
2. Check if using staged vs active
3. Click "Activate Changes" if using `/skill_roster`
4. Restart application if changed `config.yaml`

### Assignment not balanced

1. Check worker modifiers
2. Review `skill_modality_overrides` for weight tweaks
3. Verify `min_assignments_per_skill` setting
4. Check imbalance threshold (default 30%)
