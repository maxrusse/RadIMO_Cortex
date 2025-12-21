# RadIMO Admin Guide

Guide to the admin system for managing workers and schedules.

---

## Overview

RadIMO provides two admin interfaces for different operational needs:

| Page | URL | Effect | Use Case |
|------|-----|--------|----------|
| **Skill Matrix** | `/skill_roster` | Staged | Long-term planning, rotations |
| **Schedule Edit (Today)** | `/prep-next-day` | Immediate | Same-day urgent adjustments |
| **Schedule Edit (Tomorrow)** | `/prep-next-day` | Next-day only | Daily schedule preparation |

All admin pages require login with the admin password from `config.yaml`.

---

## Workflow Separation

```
┌─────────────────────────────────────────────────────────────┐
│  PLANNING (Future)              Skill Matrix                │
│  ├─ Staged changes              (Planning Mode)             │
│  ├─ Review before apply                                     │
│  └─ Activate when ready                                     │
├─────────────────────────────────────────────────────────────┤
│  SCHEDULE EDIT                  /prep-next-day              │
│  ├─ TODAY TAB (green):    Immediate live changes            │
│  │  └─ Edit current schedule, counters preserved            │
│  ├─ TOMORROW TAB (yellow): Next-day preparation             │
│  │  └─ Stage changes for auto-preload (7:30 AM)             │
│  └─ Both modes: Add/remove workers, edit times and skills   │
└─────────────────────────────────────────────────────────────┘
```

---

## 1. Skill Matrix (`/skill_roster`)

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

## 2. Schedule Edit (`/prep-next-day`)

**Purpose:** Edit schedules with two modes - immediate changes to today's schedule, or prepare tomorrow's schedule.

**Key behavior:** Dual-tab interface with different effects:
- **Change Today** tab: Immediate effect on live schedule (counters preserved)
- **Prep Tomorrow** tab: Stage changes for next workday (no immediate effect)

### When to Use

**Change Today Tab:**
- Urgent same-day schedule adjustments
- Add/remove workers from today's active schedule
- Fix shift times or skills during the workday
- **WARNING:** Changes are immediate - counters are NOT reset

**Prep Tomorrow Tab:**
- Daily schedule preparation
- Correcting mapping edge cases
- Adjusting times before auto-preload
- Testing schedule changes safely

### Interface Components

Both tabs share the same editing interface with modality-specific tables:

#### Load from CSV

Each tab has a "Load from CSV" button:
- **"Load Today"** (Change Today tab): Rebuilds today's schedule from master CSV
- **"Load Tomorrow"** (Prep Tomorrow tab): Loads next-day schedule from master CSV
- Useful for resetting manual changes or reapplying CSV after upload

#### Quick Edit Mode (Default)

**For:** Fast inline edits

- Click any cell to edit
- Edited cells highlight until saved
- Edit: worker names, times, skills, modifiers

#### Advanced Mode

**For:** Structural changes

- Toggle with "Quick Edit" button
- Add new worker rows
- Delete worker rows
- Bulk skill operations
- All Quick Edit features available

#### Filtering Controls

Both tabs include smart filters:
- **Modality filter**: Show only specific modality (CT/MR/XRAY/Mammo)
- **Skill filter**: Show only workers with specific skill active
- **Hide 0/-1 checkbox**: Hide workers with passive/excluded values for cleaner view

### Editable Fields

| Field | Format | Example |
|-------|--------|---------|
| Worker | Text | "Dr. Müller (AM)" |
| Start Time | HH:MM | "07:00" |
| End Time | HH:MM | "15:00" |
| Skills | -1, 0, 1, w | 1 (active) |
| Modifier | 0.5-1.5 | 1.0 |

### Skill Value Colors

- 🟢 **Green (1)** = Active
- 🟡 **Yellow (0)** = Passive/Fallback
- 🔴 **Red (-1)** = Excluded
- 🔵 **Blue (w)** = Weighted (visual marker)

### Example Workflows

#### Fix Wrong Shift Time (Same Day)

**Scenario:** Worker "MS" has wrong start time TODAY.

1. Go to `/prep-next-day`
2. Click **"Change Today"** tab (green header)
3. Select modality tab (CT/MR/XRAY)
4. Find "MS" in table
5. Click start_time cell, change to correct time
6. Click "Save Changes" → **Immediate effect**

#### Prepare Tomorrow's Schedule

**Scenario:** Plan tomorrow's coverage in advance.

1. Go to `/prep-next-day`
2. Click **"Prep Tomorrow"** tab (yellow header)
3. Click "Load Tomorrow" to load auto-generated schedule
4. Make adjustments as needed
5. Click "Save Changes" → Applied at next auto-preload (7:30 AM)

---

## Admin Panel (`/upload`)

Central hub for system management.

### Available Actions

| Action | Description |
|--------|-------------|
| **Medweb CSV Upload** | Upload schedule for specific date |
| **Preload Next Workday** | Manual trigger of auto-preload |
| **Force Refresh Today** | Full same-day rebuild (WARNING: destroys all counters and assignment history) |

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
3. **Same-day adjustments:** Use `/prep-next-day` → **"Change Today"** tab (immediate effect, counters preserved)
4. **End of day:** Review assignments, plan tomorrow via `/prep-next-day` → **"Prep Tomorrow"** tab

### Planning Rotations

1. Update `config.yaml` or `/skill_roster` with new skills
2. Save to staging
3. Test with `/prep-next-day` → "Prep Tomorrow" tab preview
4. Activate on rotation start day

### Same-Day Changes

**Option 1: Incremental Changes (Recommended)**
- Use `/prep-next-day` → **"Change Today"** tab
- Preserves all assignment counters and history
- Immediate effect on schedule
- Use for: worker additions, time adjustments, skill corrections

**Option 2: Full Schedule Rebuild (Use with Caution)**
- Use Admin Panel → "Force Refresh Today"
- **WARNING:** Destroys ALL counters and assignment history
- Only use when schedule structure fundamentally changes
- Document reason and time of refresh

### Skill Management

| Change Type | Use This |
|-------------|----------|
| Permanent skill change | `config.yaml` → `worker_skill_roster` |
| Temporary/rotation change | `/skill_roster` staging |
| Same-day schedule edit | `/prep-next-day` → "Change Today" tab |
| Tomorrow schedule prep | `/prep-next-day` → "Prep Tomorrow" tab |

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
4. Review `/prep-next-day` → check both "Change Today" and "Prep Tomorrow" tabs for manual deletions

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
