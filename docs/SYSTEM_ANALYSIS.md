# RadIMO SBZ - Complete System Analysis

**Note:** This document was originally created for v17 (Excel-based uploads). Some sections have been updated for v18 (medweb CSV integration).

## Table of Contents
1. [Medweb CSV Integration - v18](#medweb-csv-integration---v18) - Current workflow
2. [Time Exclusion System - v18](#time-exclusion-system---v18) - Day-specific scheduling
3. [Distribution Logic & Balancing Report](#distribution-logic--balancing-report) - Core assignment engine
   - [The Three Selection Paths](#the-three-selection-paths)
   - [Balancing Mechanisms](#balancing-mechanisms)
   - [Skill Value System (-1, 0, 1)](#skill-value-system)
   - [Fallback Mechanisms](#fallback-mechanisms)
   - [Global Cross-Modality Tracking](#global-cross-modality-tracking)
4. [Modular Architecture Report](#modular-architecture-report) - System structure

---



## 📊 Overview

The RadIMO SBZ system manages Excel-based worker schedules with sophisticated file handling that supports immediate uploads, scheduled uploads, automatic daily resets, and crash recovery through backup systems.

## 📁 File Locations

| File Type | Path | Purpose |
|-----------|------|---------|
| **Default Upload** | `uploads/SBZ_<MOD>.xlsx` | Current active schedule |
| **Scheduled Upload** | `uploads/SBZ_<MOD>_scheduled.xlsx` | Next day's schedule (activated at 7:30 AM) |
| **Live Backup** | `uploads/backups/SBZ_<MOD>_live.xlsx` | Auto-saved after every change |
| **Scheduled Backup** | `uploads/backups/SBZ_<MOD>_scheduled.xlsx` | Moved here after 7:30 reset |
| **Invalid/Quarantine** | `uploads/invalid/SBZ_<MOD>_YYYYMMDD_HHMMSS.xlsx` | Corrupted files |

---

## 🔄 File Flow Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                    STARTUP (App Launch)                      │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
        ┌──────────────────────────────────────┐
        │ Does live backup exist?               │
        │ uploads/backups/SBZ_<MOD>_live.xlsx  │
        └──────────────────────────────────────┘
          YES │                           │ NO
              ▼                           ▼
        ┌──────────┐              ┌──────────────┐
        │ Load it  │              │ Try default  │
        └──────────┘              │ SBZ_<MOD>.xlsx│
              │                   └──────────────┘
              │                           │
              ▼                           ▼
        ┌──────────────────────────────────────┐
        │ If load fails → quarantine file      │
        └──────────────────────────────────────┘
                            │
                            ▼
        ┌──────────────────────────────────────┐
        │ If both fail → start empty           │
        └──────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│              MANUAL UPLOAD (Admin /upload)                   │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
        ┌──────────────────────────────────────┐
        │ Immediate or Scheduled?               │
        └──────────────────────────────────────┘
          IMMEDIATE │                  │ SCHEDULED
                    ▼                  ▼
          ┌──────────────┐    ┌────────────────────┐
          │ Reset counters│    │ Save to scheduled │
          │ Load NOW      │    │ path (wait 7:30)  │
          │ Create backup │    └────────────────────┘
          └──────────────┘

┌─────────────────────────────────────────────────────────────┐
│            DAILY RESET (Every request >= 7:30)               │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
        ┌──────────────────────────────────────┐
        │ Is it a new day + time >= 7:30?      │
        └──────────────────────────────────────┘
          YES │                           │ NO
              ▼                           ▼
        ┌──────────────────────┐    ┌──────────┐
        │ For each modality:   │    │ Continue │
        │ 1. Reset counters    │    └──────────┘
        │ 2. Load scheduled    │
        │ 3. Move to backup    │
        │ 4. Update live       │
        └──────────────────────┘
```

---

## 📝 Excel File Structure

### Required Columns

| Column | Type | Description |
|--------|------|-------------|
| **PPL** | Text | Worker name (unique identifier) |
| **von** | Time | Shift start time (HH:MM format) |
| **bis** | Time | Shift end time (HH:MM format) |
| **Normal** | Integer | Skill value: 1=active, 0=passive, -1=excluded |
| **Notfall** | Integer | Skill value: 1=active, 0=passive, -1=excluded |
| **Privat** | Integer | Skill value: 1=active, 0=passive, -1=excluded |
| **Herz** | Integer | Skill value: 1=active, 0=passive, -1=excluded |
| **Msk** | Integer | Skill value: 1=active, 0=passive, -1=excluded |
| **Chest** | Integer | Skill value: 1=active, 0=passive, -1=excluded |
| **Modifier** | Float | Worker-specific weight modifier (default: 1.0) |

### Skill Value Meanings

- **1** = Active (used for primary requests and fallback)
- **0** = Passive (only used in fallback, not for primary)
- **-1** = Excluded (not available in fallback)

See [Skill Value System](#skill-value-system) for detailed explanation and examples.

### Example Excel File

```
| PPL  | von  | bis  | Normal | Notfall | Privat | Herz | Msk | Chest | Modifier |
|------|------|------|--------|---------|--------|------|-----|-------|----------|
| Anna | 8:00 | 16:00|   1    |    1    |   0    |  1   |  1  |   0   |   1.0    |
| Max  | 8:00 | 16:00|   1    |   -1    |   1    |  0   |  1  |   1   |   1.0    |
| Lisa | 9:00 | 17:00|   1    |    1    |   1    |  1   |  0  |   1   |   1.1    |
```

### Sheet Structure

Excel files must contain at minimum:
- **Tabelle1**: Main worker schedule data (required)
- **Tabelle2**: Optional info texts/notes (preserved during backup)

---

## ⚙️ File Operation Details

### 1. Startup Initialization
**Location:** `app.py:1457-1506`

**Priority Order:**
1. Try `uploads/backups/SBZ_<MOD>_live.xlsx`
2. If fails, try `uploads/SBZ_<MOD>.xlsx`
3. If both fail, start empty

**Behavior:**
- Corrupted files automatically quarantined
- Logs every attempt with context
- Gracefully handles missing files

**Code:**
```python
for mod, d in modality_data.items():
    backup_path = f"uploads/backups/SBZ_{mod.upper()}_live.xlsx"

    if os.path.exists(backup_path):
        if attempt_initialize_data(backup_path, mod, remove_on_failure=True):
            # Success - backup loaded
        else:
            # Backup corrupted - try default

    if not loaded and os.path.exists(d['default_file_path']):
        # Try default file...
```

---

### 2. Manual Upload
**Location:** `app.py:1583-1622`

#### **Immediate Upload** (`scheduled_upload=0`)

**Process:**
1. Validate file extension (.xlsx)
2. Reset ALL counters (draw_counts, skill_counts, WeightedCounts, global)
3. Save to `uploads/SBZ_<MOD>.xlsx`
4. Parse and validate Excel structure
5. Create live backup
6. On error: Quarantine file, return error to user

**Code:**
```python
if scheduled == '0':  # Immediate
    # Reset counters BEFORE loading
    d['draw_counts'] = {}
    d['skill_counts'] = {skill: {} for skill in SKILL_COLUMNS}
    d['WeightedCounts'] = {}
    global_worker_data['weighted_counts_per_mod'][modality] = {}
    global_worker_data['assignments_per_mod'][modality] = {}

    # Save and load
    file.save(d['default_file_path'])
    initialize_data(file_path, modality)
    backup_dataframe(modality)  # Create live backup
```

**Counter Reset Behavior:**
- Resets happen BEFORE loading new file
- Both local and global counters cleared
- Prevents old assignments carrying over

#### **Scheduled Upload** (`scheduled_upload=1`)

**Process:**
1. Validate file extension
2. Save to `uploads/SBZ_<MOD>_scheduled.xlsx`
3. Wait for daily reset at 7:30

**Code:**
```python
if scheduled == '1':
    file.save(d['scheduled_file_path'])  # Just save, don't load
    return redirect(...)
```

**Important:** Scheduled files are NOT validated until 7:30 reset!

---

### 3. Daily Reset
**Location:** `app.py:1325-1387`

**Trigger:** `@app.before_request` on EVERY request

**Conditions:**
```python
if global_worker_data['last_reset_date'] != today and now.time() >= time(7, 30):
```

**Process for Each Modality:**

1. Check if `last_reset_date != today` and `time >= 7:30`
2. Check if scheduled file exists
3. Reset counters (draw_counts, skill_counts, WeightedCounts)
4. Load scheduled file with `attempt_initialize_data(remove_on_failure=True)`
5. Move scheduled file to `uploads/backups/SBZ_<MOD>_scheduled.xlsx`
6. Create new live backup
7. Update `last_reset_date = today`
8. Reset global counters for modality

**Code:**
```python
for mod, d in modality_data.items():
    if d['last_reset_date'] == today:
        continue  # Already reset today

    if now.time() >= time(7, 30):
        if os.path.exists(d['scheduled_file_path']):
            # Reset counters
            d['draw_counts'] = {}
            d['skill_counts'] = {skill: {} for skill in SKILL_COLUMNS}
            d['WeightedCounts'] = {}

            # Load and move
            success = attempt_initialize_data(d['scheduled_file_path'], mod, remove_on_failure=True)
            if success:
                shutil.move(d['scheduled_file_path'], backup_file)
                backup_dataframe(mod)

        # Mark as reset today
        d['last_reset_date'] = today
        global_worker_data['weighted_counts_per_mod'][mod] = {}
        global_worker_data['assignments_per_mod'][mod] = {}
```

**Global Reset Logic:**
```python
# Global reset happens ONCE per day when ANY modality has a scheduled file
if global_worker_data['last_reset_date'] != today and now.time() >= time(7, 30):
    should_reset_global = any(
        os.path.exists(modality_data[mod]['scheduled_file_path'])
        for mod in allowed_modalities
    )
    if should_reset_global:
        global_worker_data['last_reset_date'] = today
```

---

### 4. File Quarantine
**Location:** `app.py:696-715`

**Purpose:** Isolate corrupted Excel files for inspection

**Process:**
1. Create `uploads/invalid/` directory
2. Generate timestamped filename: `SBZ_<MOD>_YYYYMMDD_HHMMSS.xlsx`
3. Move file (not copy) to quarantine
4. Log warning with reason
5. On move failure: Log warning but don't crash

**Code:**
```python
def quarantine_excel(file_path: str, reason: str):
    invalid_dir = Path(app.config['UPLOAD_FOLDER']) / 'invalid'
    invalid_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    target = invalid_dir / f"{original.stem}_{timestamp}.xlsx"

    shutil.move(str(original), str(target))
    selection_logger.warning("Defekte Excel '%s' nach '%s' verschoben (%s)", ...)
```

**Triggered When:**
- Startup: Corrupted live backup or default file
- Upload: Invalid Excel structure
- Daily reset: Corrupted scheduled file

---

### 5. Live Backup
**Location:** `app.py:1422-1451`

**Purpose:** Auto-save current state after changes

**Process:**
1. Create `uploads/backups/` directory
2. Export DataFrame WITHOUT runtime columns (start_time, end_time, shift_duration)
3. Write to `SBZ_<MOD>_live.xlsx`
4. Include "Tabelle1" (data) and "Tabelle2" (info texts)

**Triggered When:**
- Immediate upload
- Daily reset (after loading scheduled file)
- Edit entry (after manual changes)
- Delete entry

**Code:**
```python
def backup_dataframe(modality: str):
    # Remove runtime columns
    cols_to_backup = [col for col in df.columns
                      if col not in ['start_time', 'end_time', 'shift_duration']]
    df_backup = d['working_hours_df'][cols_to_backup].copy()

    with pd.ExcelWriter(backup_file, engine='openpyxl') as writer:
        df_backup.to_excel(writer, sheet_name='Tabelle1', index=False)
        if d.get('info_texts'):
            df_info.to_excel(writer, sheet_name='Tabelle2', index=False)
```

---

## 📋 File Lifecycle Summary

### Typical Daily Flow

```
Day 1:
08:00 - Admin uploads schedule for tomorrow (scheduled_upload=1)
        → Saved to uploads/SBZ_CT_scheduled.xlsx
        → Not validated or loaded yet

Day 2:
07:29:59 - Last assignments using Day 1 schedule
07:30:00 - First request after 7:30
           → check_and_perform_daily_reset() triggered
           → Counters reset
           → scheduled file loaded
           → scheduled file moved to backups/
           → live backup created
07:30:01 - New assignments use Day 2 schedule

12:00 - Admin makes manual edit
        → live backup updated

Day 3:
07:30 - Repeat...
```

---

## 📊 File Size & Performance

**Typical Excel File:** ~50KB - 500KB
**Live Backup:** Same size (no compression)
**Startup Time:** ~100ms per modality to load Excel
**Daily Reset:** ~200ms (load + move + backup)

**Disk Usage Estimate** (3 modalities, 30 days):
```
Current files:      3 × 500KB = 1.5 MB
Live backups:       3 × 500KB = 1.5 MB
Daily backups:      3 × 30 × 500KB = 45 MB
Quarantined files:  Variable (depends on errors)
Total:             ~50 MB/month
```

---

## 🔒 Security Considerations

✅ **File Type Validation:** Only .xlsx allowed
✅ **Admin Authentication:** Upload requires login
✅ **Path Traversal:** Using Path() prevents ../.. attacks
✅ **Quarantine Isolation:** Bad files moved to separate directory
⚠️ **File Size Limits:** Not enforced (Flask default: 16MB)
⚠️ **Malicious Excel:** No virus scanning (assumes trusted admins)

</details>

---

# Medweb CSV Integration - v18

## 📊 Overview

RadIMO v18 uses **config-driven medweb CSV integration** to directly ingest worker schedules without manual Excel file creation. This approach provides better maintainability, flexibility, and automation.

## 🔄 Architecture

```
medweb.csv (monthly schedule)
    ↓
Config-driven parsing (medweb_mapping rules)
    ↓
Worker skill roster overrides
    ↓
Time exclusion processing (boards, meetings)
    ↓
working_hours_df per modality
    ↓
Real-time assignment system
```

## ⚙️ Key Components

### 1. Medweb Mapping Rules

Activities from medweb CSV are mapped to modalities and skills via `config.yaml`:

```yaml
medweb_mapping:
  rules:
    - match: "CT Spätdienst"
      modality: "ct"
      shift: "Spaetdienst"
      base_skills: {Normal: 1, Notfall: 1, Privat: 0, ...}
```

**How Matching Works:**
- Case-insensitive substring matching
- First matching rule wins
- Unmapped activities are ignored

### 2. Worker Skill Roster

Per-worker skill overrides with modality-specific configuration:

```yaml
worker_skill_roster:
  AAn:  # Worker abbreviation
    default:  # All modalities
      Msk: 1  # MSK specialist
    ct:  # CT-specific override
      Notfall: 0  # Only fallback for CT Notfall
```

**Precedence:** `worker_skill_roster` > `medweb_mapping` > system defaults

### 3. Auto-Preload System

**Schedule:** Daily at 7:30 AM CET
**Source:** `uploads/master_medweb.csv`
**Logic:** Friday → Monday, other days → tomorrow
**Mechanism:** APScheduler with CronTrigger

**How It Works:**
1. Calculates next workday date
2. Parses medweb CSV for that date
3. Prepares worker schedules with skill assignments
4. Saves to `uploads/SBZ_<MOD>_scheduled.xlsx` files
5. These files are activated at 7:30 AM on the target date via daily reset

**Important:** Auto-preload prepares tomorrow's schedule without affecting today's active assignments. The new schedule only becomes active when the date changes.

### 4. Upload Strategies

- **Manual Upload:** Any date, immediate processing
- **Preload Next Day:** Manual trigger for tomorrow
- **Force Refresh:** Emergency same-day reload (destroys counters)

**Detailed Documentation:** See [WORKFLOW.md](WORKFLOW.md)

---

# Time Exclusion System - v18

## 📊 Overview

The time exclusion system **punches out time** from worker shifts for boards, meetings, teaching, and other non-work activities. This allows workers to have complex schedules with interruptions.

## 🔧 Configuration

Time exclusions are **day-specific** - same activity can have different times per weekday:

```yaml
medweb_mapping:
  rules:
    - match: "Kopf-Hals-Board"
      exclusion: true
      schedule:
        Montag: "15:30-17:00"  # Only applies on Mondays
      prep_time:
        before: "30m"  # Prep time: 15:00-15:30
        after: "15m"   # Cleanup: 17:00-17:15

    - match: "Board"
      exclusion: true
      schedule:
        Dienstag: "15:00-17:00"
        Mittwoch: "10:00-12:00"
        Donnerstag: "14:00-16:00"
```

## ⚙️ How It Works

### 1. CSV Entry Detection

When CSV contains exclusion activity for a worker:
```
"24.11.2025","NM","ZANDERCH","CZ","Charlotte Dr Zander",...,"Kopf-Hals-Board",...
```

### 2. Schedule Lookup

- Get weekday name: `get_weekday_name_german(target_date)` → "Montag"
- Check if schedule exists: `schedule["Montag"]` → "15:30-17:00"
- If no schedule for this weekday → activity ignored (doesn't apply today)

### 3. Prep Time Extension (Optional)

```
Base exclusion:     [15:30 ───── 17:00]
With prep_time:
  before: "30m" →  [15:00
  after: "15m"   →           17:15]

Final exclusion:    [15:00 ────── 17:15]
```

### 4. Shift Splitting

Worker's original shift: `07:00-21:00`
After exclusion applied: `07:00-15:00` + `17:15-21:00`

```
Original:  [07:00 ────────────────────────── 21:00]
Exclusion:              [15:00 ─── 17:15]

Result:    [07:00 ──── 15:00] [17:15 ──── 21:00]
```

## 🔄 Processing Algorithm

### Two-Pass System

**FIRST PASS - Collect exclusions and work shifts:**
1. For each CSV row:
   - Match against `medweb_mapping.rules`
   - If `exclusion: true`:
     - Check if weekday in schedule
     - Parse time range
     - Apply prep_time extensions
     - Store in `exclusions_per_worker[canonical_id]`
     - Skip adding to work shifts
   - If normal work:
     - Add to `rows_per_modality[modality]`

**SECOND PASS - Apply exclusions:**
2. Group shifts by worker
3. For workers with exclusions:
   - Call `apply_exclusions_to_shifts()`
   - Splits/truncates shifts at exclusion boundaries
   - Handles multiple overlapping exclusions
   - Minimum segment: 0.1h (6 minutes)

### Example with Multiple Exclusions

```
Original shift:    [07:00 ────────────────────────── 21:00]

Exclusions:
  Board:                  [10:00 ── 12:00]
  Fortbildung:                        [15:00 ──── 17:00]

Result:            [07:00 ─ 10:00] [12:00 ─ 15:00] [17:00 ─ 21:00]
```

## 📝 Logging

```
INFO: Time exclusion for Charlotte Dr Zander (CZ) (Montag): 15:00-17:15 (Kopf-Hals-Board)
INFO: Applying time exclusions for 3 workers on Montag
```

## ✅ Benefits

- ✅ **No time parsing needed** - Time range in config, not CSV description
- ✅ **Day-specific** - Board on Monday ≠ Board on Tuesday
- ✅ **Prep time support** - Automatic before/after extension
- ✅ **Multiple exclusions** - Handles overlapping correctly
- ✅ **Config-driven** - Add new exclusions without code changes

---

# Distribution Logic & Balancing Report

## 🎯 Overview

The RadIMO SBZ system implements **three distinct worker selection strategies** (the "3 Paths") that can be configured via `config.yaml`. Each strategy optimizes for different prioritization goals while maintaining fair load distribution across workers.

## 🔀 The Three Selection Paths

### Configuration
**Location:** `config.yaml` - Line 116
```yaml
balancer:
  fallback_strategy: skill_priority  # Options: skill_priority, modality_priority, pool_priority
```

### Main Entry Point
**Function:** `get_next_available_worker()`
**Location:** `app.py:974-987`

Routes incoming requests to the appropriate selection strategy:

```python
def get_next_available_worker(
    current_dt: datetime,
    role='normal',
    modality=default_modality,
    allow_fallback: bool = True,
):
    strategy = BALANCER_SETTINGS.get('fallback_strategy', 'skill_priority')

    if strategy == 'modality_priority':
        return _get_worker_modality_priority(...)
    elif strategy == 'pool_priority':
        return _get_worker_pool_priority(...)
    else:
        return _get_worker_skill_priority(...)
```

---

## Path 1: SKILL_PRIORITY (Default Strategy)

**Function:** `_get_worker_skill_priority()`
**Location:** `app.py:990-1049`

### Strategy
**"Try all skill fallbacks per modality BEFORE moving to next modality"**

### Search Order
```
For each modality in search chain:
  └─ Try requested skill
     └─ Try all skill fallbacks
        └─ Return best match
           └─ If none found, move to next modality
```

### How It Works
1. Searches the requested modality first
2. Uses the configured skill fallback chain for that modality
3. Only moves to fallback modalities after exhausting all skills
4. Returns first match found with best worker ratio

### Example Flow
**Request:** CT / Privat

```
1. Try CT → Privat
2. Try CT → Notfall
3. Try CT → Normal
4. Try MR → Privat (if modality fallback configured)
5. Try MR → Notfall
6. Try MR → Normal
```

### Best For
- **Primary modality-focused assignment**
- Keep workers in their primary modality
- Stay in CT and try all skills before going to MR
- Typical radiology workflows where modality expertise matters

### Code Structure
```python
def _get_worker_skill_priority(current_dt, role, modality, allow_fallback):
    # Build modality search order
    modality_chain = [modality] + get_modality_fallbacks(modality)

    # Try each modality
    for current_mod in modality_chain:
        # Try primary role + all skill fallbacks
        result = get_active_df_for_role(current_dt, role, current_mod, allow_fallback)
        if result:
            return result

    return None  # No worker found
```

---

## Path 2: MODALITY_PRIORITY (Cross-Modality Strategy)

**Function:** `_get_worker_modality_priority()`
**Location:** `app.py:1052-1178`

### Strategy
**"Try each skill across ALL modalities before moving to next skill fallback"**

### Search Order
```
For each skill in fallback chain:
  └─ Try across all modalities in parallel
     └─ Return best match globally
        └─ If none found, move to next skill
```

### How It Works
1. Builds skill fallback sequence from the requested role
2. Builds modality search order (primary + fallbacks)
3. For EACH skill, searches ALL modalities simultaneously
4. Returns best match when skill is found anywhere
5. Logs when using fallback

### Example Flow
**Request:** CT / Privat

```
1. Try Privat across: CT, MR, XRAY (all modalities)
   → Pick best from all candidates
2. If none: Try Notfall across: CT, MR, XRAY
   → Pick best from all candidates
3. If none: Try Normal across: CT, MR, XRAY
   → Pick best from all candidates
```

### Best For
- **Skill-focused assignment**
- When skill expertise is more important than modality
- Ensure specific skill is used before falling back
- Flexible cross-training environments

### Code Structure
```python
def _get_worker_modality_priority(current_dt, role, modality, allow_fallback):
    # Build skill fallback sequence
    skill_fallback_sequence = _build_skill_fallback_sequence(role, modality, allow_fallback)

    # Build modality search order
    modality_search_order = [modality] + get_modality_fallbacks(modality)

    # For each skill tier
    for skill_tier in skill_fallback_sequence:
        candidates = []

        # Try across all modalities
        for mod in modality_search_order:
            result = _select_worker_for_modality(current_dt, skill_tier, mod, ...)
            if result:
                candidates.append((result, mod, skill_tier))

        # Return best from all modalities
        if candidates:
            return _pick_best_candidate(candidates)

    return None
```

---

## Path 3: POOL_PRIORITY (Optimal Global Load Balancing)

**Function:** `_get_worker_pool_priority()`
**Location:** `app.py:1181-1322`

### Strategy
**"Build pool of all CONFIGURED (skill, modality) combinations and pick globally best worker"**

### Search Order
```
Build skill chain from configured fallbacks
Build modality chain from configured fallbacks
Create pool: skill_chain × modality_chain (respecting config)
Evaluate EVERY configured combination simultaneously
Score each using weighted_ratio
Return single globally-best candidate
```

### How It Works
1. Builds skill fallback sequence from `BALANCER_FALLBACK_CHAIN` configuration
2. Builds modality search order from `MODALITY_FALLBACK_CHAIN` configuration
3. Creates combinations ONLY from these configured chains (not blind all×all)
4. Evaluates every configured combination at once
5. Uses `weighted_ratio` to score each combination
6. Returns single globally-best candidate from entire pool
7. Logs pool size and selection details

### Example Flow
**Request:** CT / Privat

**With config.yaml:**
```yaml
balancer:
  fallback_chain:
    Privat: [Notfall, [Normal, Herz]]

modality_fallbacks:
  ct: [mr]
```

**Pool built:**
```
Skill chain: Privat → Notfall → Normal, Herz
Modality chain: CT → MR

Build pool from CONFIGURED combinations:
  CT × Privat
  CT × Notfall
  CT × Normal
  CT × Herz
  MR × Privat
  MR × Notfall
  MR × Normal
  MR × Herz

Evaluate all 8 configured combinations
Pick worker with lowest weighted_ratio across all
```

### Best For
- **Optimal global load distribution**
- Prevent repeated selection of same person
- Balance work across ALL dimensions simultaneously
- Maximum fairness across skills AND modalities

### Key Advantage
Compares against **global work across modalities**, preventing scenarios like:
- Worker A: 10 CT assignments, 0 MR assignments
- Worker B: 0 CT assignments, 0 MR assignments
- System picks Worker B even though both available for CT

### Code Structure
```python
def _get_worker_pool_priority(current_dt, role, modality, allow_fallback):
    # Build skill fallback chain from BALANCER_FALLBACK_CHAIN config
    primary_skill = role_map[role.lower()]
    skill_chain = [primary_skill]

    if allow_fallback:
        configured_fallbacks = BALANCER_FALLBACK_CHAIN.get(primary_skill, [])
        for fallback_entry in configured_fallbacks:
            if isinstance(fallback_entry, list):
                skill_chain.extend(fallback_entry)
            else:
                skill_chain.append(fallback_entry)

    # Build modality search order from MODALITY_FALLBACK_CHAIN config
    modality_search = [modality] + MODALITY_FALLBACK_CHAIN.get(modality, [])

    # Build pool from CONFIGURED combinations only
    candidate_pool = []
    for skill_to_try in skill_chain:
        for target_modality in modality_search:
            # Filter active workers
            active_df = d['working_hours_df'][
                (d['working_hours_df']['start_time'] <= current_time) &
                (d['working_hours_df']['end_time'] >= current_time)
            ]

            # Try this specific (skill, modality) combination
            selection = _attempt_column_selection(active_df, skill_to_try, target_modality)
            balanced_df = _apply_minimum_balancer(selection, skill_to_try, target_modality)

            # Calculate weighted ratio for best worker in this combination
            best_person = sorted(available_workers, key=lambda p: weighted_ratio(p))[0]
            ratio = weighted_ratio(best_person)

            candidate_pool.append((ratio, candidate, skill_to_try, target_modality))

    # Pick globally best from entire pool
    if candidate_pool:
        ratio, candidate, used_skill, source_modality = min(candidate_pool, key=lambda item: item[0])
        return candidate, used_skill, source_modality

    return None
```

---

## 🔄 Balancing Mechanisms

### 1. Effective Assignment Load Calculation
**Function:** `_get_effective_assignment_load()`
**Location:** `app.py:748-773`

Combines local and global work tracking to avoid overworking anyone:

```python
def _get_effective_assignment_load(worker, column, modality):
    # Local count: this modality/skill
    local_count = skill_counts.get(worker, 0)

    # Global count: all modalities weighted
    canonical_id = get_canonical_worker_id(worker)
    global_weighted_total = get_global_weighted_count(canonical_id)

    # Use the HIGHER value
    return max(local_count, global_weighted_total)
```

**Key Insight:** Using `max()` ensures work done in OTHER modalities counts against minimum balancer checks.

---

### 2. Minimum Balancer (Two-Phase)
**Function:** `_apply_minimum_balancer()`
**Location:** `app.py:1585-1660`

Ensures fair distribution using a **two-phase approach** to prevent worker overload:

#### Phase 1: No-Overflow Mode
Until **ALL ACTIVE workers** (skill >= 1) for this skill have at least `min_required` **WEIGHTED** assignments, restrict selection to only workers below the threshold. This ensures round-robin distribution where everyone gets their fair share before anyone gets overloaded.

#### Phase 2: Normal Mode
Once all active workers with this skill have the minimum weighted assignments, return all currently active workers and allow normal weighted selection with overflow based on hours worked.

```python
def _apply_minimum_balancer(filtered_df, column, modality):
    if not BALANCER_SETTINGS.get('enabled', True):
        return filtered_df

    min_required = BALANCER_SETTINGS.get('min_assignments_per_skill', 0)

    # Get working_hours_df to check skill values
    working_hours_df = modality_data[modality].get('working_hours_df')
    skill_counts = modality_data[modality]['skill_counts'].get(column, {})

    # Check ONLY ACTIVE workers (skill >= 1)
    # Workers with skill = 0 (passive) are NOT counted toward minimums
    any_below_minimum = False
    for worker in skill_counts.keys():
        worker_rows = working_hours_df[working_hours_df['PPL'] == worker]
        skill_value = worker_rows[column].iloc[0]

        if skill_value < 1:  # Skip passive (0) and excluded (-1)
            continue

        # Check weighted assignment load
        count = _get_effective_assignment_load(worker, column, modality)
        if count < min_required:
            any_below_minimum = True
            break

    # Phase 2: All active workers have minimum → return full pool
    if not any_below_minimum:
        return filtered_df

    # Phase 1: Some active workers below minimum → restrict pool
    prioritized = filtered_df[
        filtered_df['PPL'].apply(
            lambda worker: _get_effective_assignment_load(worker, column, modality) < min_required
        )
    ]

    return prioritized if not prioritized.empty else filtered_df
```

**Key Features:**
- ✅ **Only counts ACTIVE workers** (skill >= 1) - Passive (0) and excluded (-1) workers are NOT counted
- ✅ **Uses WEIGHTED assignments** - Task with weight 1.5 counts as 1.5, not "1"
- ✅ **Checks ALL workers with skill** - Not just currently active (prevents midday shift issues)
- ✅ **Two-phase logic** - No-overflow until minimum reached, then normal mode

**Configuration:** `config.yaml:113`
```yaml
min_assignments_per_skill: 3.0  # Weighted assignments required (recommended: 2-3)
```

**Example Scenario:**
With `min_required=3.0` (weighted):
- Worker A (Normal=1): 2.5 weighted → below minimum (Phase 1)
- Worker B (Normal=1): 3.5 weighted → above minimum
- Worker C (Normal=0): 0.0 weighted → NOT counted (passive worker)
- **Result:** System stays in Phase 1, restricts pool to workers below 3.0

Once Worker A reaches 3.0 weighted, Phase 2 activates and all currently active workers are eligible for normal weighted selection.

---

### 3. State Persistence
**Functions:** `save_state()` / `load_state()`
**Location:** `app.py:537-611`
**File:** `uploads/fairness_state.json`

**Purpose:** Maintains fairness counters across server restarts to ensure consistent load balancing throughout the day.

**What is Saved:**
- Worker assignment counts per skill and modality
- Weighted assignment totals (accounts for task difficulty)
- Global worker tracking across all modalities
- Last reset date for each modality

**When State is Saved:**
- After every assignment
- After daily reset
- After CSV upload

**When State is Loaded:**
- During app initialization (on startup)

**Benefits:**
- Counters persist across server restarts
- Fair distribution maintained even after deployments
- No loss of workload history during the day

---

### 4. Imbalance Detection
**Function:** `_should_balance_via_fallback()`
**Location:** `app.py:798-827`

Triggers fallback when assignment distribution becomes unfair:

```python
def _should_balance_via_fallback(worker_counts, modality):
    if not BALANCER_SETTINGS.get('allow_fallback_on_imbalance', True):
        return False

    if len(worker_counts) < 2:
        return False

    threshold_pct = BALANCER_SETTINGS.get('imbalance_threshold_pct', 30)
    max_count = max(worker_counts)
    min_count = min(worker_counts)

    # Calculate percentage imbalance
    imbalance = (max_count - min_count) / max_count

    return imbalance >= (threshold_pct / 100.0)
```

**Configuration:** `config.yaml:114`
```yaml
imbalance_threshold_pct: 30  # If 30% difference detected, use fallback
```

**Example:**
- Worker A: 10 assignments
- Worker B: 7 assignments
- Imbalance = (10 - 7) / 10 = 30% → **TRIGGER FALLBACK**

---

### 4. Worker Selection for Specific Modality
**Function:** `_select_worker_for_modality()`
**Location:** `app.py:911-971`

Core function that selects best worker from available pool:

#### Process
1. **Filter by Time:** Only active workers (current time within their shift)
2. **Filter by Skill:** Apply role mapping to skill columns
3. **Apply Minimum Balancer:** Prioritize underutilized workers
4. **Calculate Weighted Ratio:** Score based on work hours and global weighted count
5. **Select Best:** Pick worker with lowest ratio (least loaded)

#### Key Calculation - Weighted Ratio
**Location:** `app.py:954-958`

```python
def weighted_ratio(person):
    canonical_id = get_canonical_worker_id(person)
    h = hours_map.get(canonical_id, 0)  # Work hours this modality
    w = get_global_weighted_count(canonical_id)  # Total weighted assignments
    return w / h if h > 0 else w  # Normalize by available hours
```

**Formula:**
```
weighted_ratio = global_weighted_assignments / available_work_hours

Lower ratio = more available = SELECTED
```

#### Example
```
Worker A: 15 weighted assignments, 8 hours → ratio = 15/8 = 1.875
Worker B: 10 weighted assignments, 6 hours → ratio = 10/6 = 1.667
Worker C: 5 weighted assignments, 4 hours → ratio = 5/4 = 1.250

Result: Worker C selected (lowest ratio = most available)
```

---

## 🎚️ Skill Value System

### Worker Skill Values
**Location:** Excel files, skill columns (Normal, Notfall, Privat, Herz, Msk, Chest)

Workers can have three different values for each skill column:

| Value | Name | Behavior | Use Case |
|-------|------|----------|----------|
| **1** | **Active** | Available for both primary requests AND fallback | Standard worker assignment |
| **0** | **Passive** | Available ONLY in fallback, NOT for primary requests | Worker can help if needed but shouldn't be first choice |
| **-1** | **Excluded** | NOT available in fallback (has skill but excluded) | Worker has skill but is reserved/unavailable |

### Selection Logic
**Function:** `_attempt_column_selection()`
**Location:** `app.py:830-859`

```python
def _attempt_column_selection(active_df, column, modality, is_primary=True):
    if is_primary:
        # Primary selection: only workers with value >= 1 (active workers)
        filtered_df = active_df[active_df[column] >= 1]
    else:
        # Fallback selection: workers with value >= 0 (includes passive, excludes -1)
        filtered_df = active_df[active_df[column] >= 0]
```

### Practical Examples

#### Example 1: Passive Workers (Value = 0)
```
Worker: Anna
Skill: Privat = 0

Request: /api/ct/privat (primary request for Privat)
Result: Anna NOT selected (value 0 < 1, not active for primary)

Request: /api/ct/herz (primary request for Herz, fallback to Privat)
Result: Anna CAN be selected (value 0 >= 0, available in fallback)
```

**Use Case:** Anna knows Privat but prefers other skills. Use her only when no active Privat workers available.

#### Example 2: Excluded Workers (Value = -1)
```
Worker: Max
Skill: Notfall = -1

Request: /api/ct/notfall (primary request for Notfall)
Result: Max NOT selected (value -1 < 1, not active)

Request: /api/ct/herz (primary request for Herz, fallback to Notfall)
Result: Max NOT selected (value -1 < 0, excluded from fallback)
```

**Use Case:** Max has Notfall certification but is currently in training and should not be assigned to Notfall cases.

#### Example 3: Mixed Values
```
Workers:
  - Lisa: Privat = 1  (active)
  - Tom:  Privat = 0  (passive)
  - Sara: Privat = -1 (excluded)

Request: /api/ct/privat
Result: Only Lisa eligible for primary selection

Request: /api/ct/herz → fallback to Privat
Result: Lisa AND Tom eligible for fallback (Sara excluded)
```

### Implementation Details

**Primary vs. Fallback Detection:**
```python
# In modality_priority and pool_priority strategies:
for skill_to_try in skill_chain:
    is_primary_skill = (skill_to_try == primary_skill)  # True only for first skill
    selection = _attempt_column_selection(
        active_df,
        skill_to_try,
        target_modality,
        is_primary=is_primary_skill  # Changes filtering behavior
    )
```

**Fallback Chain Handling:**
```python
# In _try_configured_fallback():
for fallback_column in fallback_chain:
    # Always use is_primary=False for fallback chains
    result = _attempt_column_selection(
        active_df,
        fallback_column,
        modality,
        is_primary=False  # Allows passive workers (value 0)
    )
```

### Configuration in Excel

**Example Excel Structure:**
```
| PPL  | von  | bis  | Normal | Notfall | Privat | Herz | Modifier |
|------|------|------|--------|---------|--------|------|----------|
| Anna | 8:00 | 16:00|   1    |    1    |   0    |  1   |   1.0    |
| Max  | 8:00 | 16:00|   1    |   -1    |   1    |  0   |   1.0    |
| Lisa | 9:00 | 17:00|   1    |    1    |   1    |  1   |   1.0    |
```

**Interpretation:**
- **Anna:** Active for Normal, Notfall, Herz; Passive for Privat
- **Max:** Active for Normal, Privat; Passive for Herz; Excluded from Notfall
- **Lisa:** Active for all skills

### Benefits

1. **Fine-Grained Control:** Manage worker availability at skill level
2. **Training Support:** Mark workers as passive (0) during training period
3. **Temporary Exclusions:** Use -1 for workers on leave or restricted duties
4. **Fallback Optimization:** Passive workers (0) provide backup without being primary choice
5. **No Configuration Changes:** All controlled through Excel file values

---

## 🔗 Fallback Mechanisms

### 1. Column Selection (Skill Fallback)
**Function:** `_attempt_column_selection()`
**Location:** `app.py:830-840`

Tries to select from a specific skill column:

```python
def _attempt_column_selection(current_dt, column, modality, primary_column):
    # Check if column exists and has available workers
    if column not in df.columns:
        return None

    if not (df[column] > 0).any():
        return None

    # Apply minimum balancer if enabled
    result = _select_worker_for_modality(current_dt, column, modality, ...)

    # Tag with source skill
    if result:
        result['source'] = column

    return result
```

---

### 2. Configured Fallback Chain
**Function:** `_try_configured_fallback()`
**Location:** `app.py:843-861`

Walks through skill fallback chain defined in config:

```python
def _try_configured_fallback(current_dt, current_column, modality, allow_fallback):
    if not allow_fallback:
        return None

    fallback_chain = BALANCER_FALLBACK_CHAIN.get(current_column, [])

    for fallback in fallback_chain:
        if isinstance(fallback, list):
            # Grouped fallbacks (try all in parallel)
            candidates = []
            for fb_col in fallback:
                result = _attempt_column_selection(current_dt, fb_col, modality, current_column)
                if result:
                    candidates.append(result)

            # Return best from group
            if candidates:
                return min(candidates, key=lambda x: x.get('ratio', float('inf')))

        else:
            # Single fallback
            result = _attempt_column_selection(current_dt, fallback, modality, current_column)
            if result:
                return result

    return None
```

**Fallback Chain Example from config.yaml:**
```yaml
fallback_chain:
  Privat:
    - Notfall
    - [Normal, Herz]  # Parallel group - try both, pick best
  Herz:
    - [Notfall, Normal]  # Parallel group
  Msk:
    - Notfall
    - Normal
```

**Execution for Privat:**
1. Try Privat (primary)
2. Try Notfall (first fallback)
3. Try Normal AND Herz in parallel, pick best (second fallback group)

---

### 3. Role-to-Column Mapping
**Function:** `get_active_df_for_role()`
**Location:** `app.py:1748-1792`

Maps request role to skill column and applies fallback strategy.

**Strict Mode Behavior:**
When `allow_fallback=False` (strict mode via * button), the system:
- Uses ONLY the requested skill column
- Skips all configured fallback chains
- Skips automatic imbalance-based fallback
- Returns only workers with the exact skill requested

**Normal Mode Behavior:**
When `allow_fallback=True` (default), the system:
- Tries the requested skill first
- Falls back through configured skill chains if needed
- Can trigger additional fallback if imbalance detected
- Maximizes chance of finding an available worker

**Example:**
```
Request: CT/Herz with strict mode
→ Only returns workers with Herz=1 in CT
→ Will NOT fallback to Notfall or Normal even if Herz workers are busy

Request: CT/Herz with normal mode
→ Tries Herz first
→ Falls back to Notfall → Normal if needed
→ May also check MR/Herz if CT is imbalanced
```

---

## 🌍 Global Cross-Modality Tracking

### Data Structure
**Location:** `app.py:424-430`

Tracks work across all modalities to prevent overassignment:

```python
global_worker_data = {
    'worker_ids': {},  # name → canonical_id mapping
    'weighted_counts_per_mod': {
        'ct': {},   # canonical_id → weighted_count
        'mr': {},
        'xray': {}
    },
    'assignments_per_mod': {
        'ct': {},   # canonical_id → raw_count
        'mr': {},
        'xray': {}
    },
    'last_reset_date': None  # Daily reset tracking
}
```

---

### Weight Calculation
**Function:** `update_global_assignment()`
**Location:** `app.py:1405-1419`

```python
def update_global_assignment(person, role, modality):
    canonical_id = get_canonical_worker_id(person)

    # Get worker-specific modifier from Excel
    modifier = modality_data[modality]['worker_modifiers'].get(person, 1.0)

    # Get skill weight from config
    skill_weights = {
        'Normal': 1.0,
        'Notfall': 1.1,
        'Privat': 1.2,
        'Herz': 1.2,
        'Msk': 0.8,
        'Chest': 0.8
    }

    # Get modality factor from config
    modality_factors = {
        'ct': 1.0,
        'mr': 1.2,
        'xray': 0.33
    }

    # Calculate weighted assignment
    weight = (
        skill_weights.get(role, 1.0) *
        modifier *
        modality_factors.get(modality, 1.0)
    )

    # Update global tracking
    global_worker_data['weighted_counts_per_mod'][modality][canonical_id] += weight
    global_worker_data['assignments_per_mod'][modality][canonical_id] += 1
```

**Example Calculation:**
```
Assignment: Worker "Max" → Privat skill → MR modality
Modifier from Excel: 1.1
Skill weight (Privat): 1.2
Modality factor (MR): 1.2

Weighted assignment = 1.2 × 1.1 × 1.2 = 1.584
```

---

## 🎛️ API Endpoints for Selection

### Assignment Endpoint
**Route:** `/api/<modality>/<role>`
**Location:** `app.py:1699-1704`

```python
@app.route('/api/<modality>/<role>')
def api_assign(modality, role):
    return _assign_worker(modality, role, allow_fallback=True)
```

**Features:**
- Full fallback enabled
- Uses configured `fallback_strategy`
- Returns worker with metadata

---

### Strict Endpoint
**Route:** `/api/<modality>/<role>/strict`
**Location:** `app.py:1707-1712`

```python
@app.route('/api/<modality>/<role>/strict')
def api_assign_strict(modality, role):
    return _assign_worker(modality, role, allow_fallback=False)
```

**Features:**
- No fallback allowed
- Returns "no person in this group" if strict requirements not met
- Used when specific skill is mandatory

---

## 📊 Balancing Configuration Summary

**Location:** `config.yaml:112-132`

```yaml
balancer:
  enabled: true                          # Activate load balancing
  min_assignments_per_skill: 5           # Fair distribution minimum
  imbalance_threshold_pct: 30            # Trigger fallback on imbalance
  allow_fallback_on_imbalance: true      # Auto-fallback when imbalanced
  fallback_strategy: skill_priority      # Which of the 3 paths to use

  fallback_chain:
    Normal: []
    Notfall: [Normal]
    Herz: [[Notfall, Normal]]            # Parallel group
    Privat: [Notfall, [Normal, Herz]]    # Sequential + parallel
    Msk: [Notfall, Normal]
    Chest: [Notfall, Normal]
```

---

## 📈 Strategy Comparison Table

| Feature | Skill Priority | Modality Priority | Pool Priority |
|---------|---------------|-------------------|---------------|
| **Primary Goal** | Keep in modality | Find specific skill | Global optimization |
| **Search Pattern** | Modality → Skills | Skill → Modalities | Configured combinations |
| **Combinations** | Sequential | Parallel per skill | All configured fallbacks |
| **Best For** | Modality expertise | Skill expertise | Maximum fairness |
| **Complexity** | Low | Medium | High |
| **Performance** | Fast | Medium | Slower (more checks) |
| **Fallback Logic** | Sequential | Parallel per skill | Global pool comparison |
| **Cross-modality** | Last resort | Preferred | Equal weight (if configured) |
| **Config Respect** | Yes | Yes | Yes (builds pool from config) |

---

## 🎯 Selection Path Examples

### Example Request: CT / Privat

#### Skill Priority Path
```
1. CT → Privat ✓ Found Worker A (ratio: 1.5)
   Return: Worker A
```

#### Modality Priority Path
```
1. Privat across all modalities:
   - CT → Privat: Worker A (ratio: 1.5)
   - MR → Privat: Worker B (ratio: 1.2)
   - XRAY → Privat: Worker C (ratio: 2.0)
   Return: Worker B (best ratio)
```

#### Pool Priority Path
```
With config:
  fallback_chain: Privat → [Notfall, [Normal, Herz]]
  modality_fallbacks: ct → [mr]

Build pool from CONFIGURED combinations:
  CT × Privat: Worker A (1.5)
  CT × Notfall: Worker D (1.1)
  CT × Normal: Worker E (0.9)
  CT × Herz: Worker J (1.3)
  MR × Privat: Worker B (1.2)
  MR × Notfall: Worker F (1.0)
  MR × Normal: Worker G (0.8)
  MR × Herz: Worker K (1.4)

Return: Worker G (lowest ratio across entire configured pool)
Note: XRAY not included - not in configured modality fallbacks
```

---

# Modular Architecture Report

## 🏗️ System Architecture Overview

The RadIMO SBZ system is organized into distinct functional modules, each responsible for specific aspects of worker assignment, file management, and system configuration.

## 📦 Core Modules

### 1. Configuration Management Module
**Lines:** `app.py:55-372`

#### Components
- **Default Constants** (55-168)
  - `DEFAULT_FALLBACK_CHAIN` - Skill fallback definitions
  - `DEFAULT_SKILLS` - Skill properties and weights
  - `DEFAULT_MODALITIES` - Modality properties and factors
  - `DEFAULT_CONFIG` - Base configuration
  - `DEFAULT_BALANCER` - Balancing settings

- **Normalization Functions** (170-243)
  - `_normalize_skill_fallback_entries()` - Process fallback chains
  - `_normalize_modality_fallback_entries()` - Process modality fallbacks
  - `_coerce_float()` - Type conversion
  - `_coerce_int()` - Type conversion

- **Config Loaders** (246-372)
  - `_load_raw_config()` - Read YAML file
  - `_merge_config()` - Merge with defaults
  - `load_config()` - Main config loader
  - `_build_modality_config()` - Process modalities
  - `_build_skills_config()` - Process skills
  - `_build_balancer_config()` - Process balancer settings

#### Purpose
Provides centralized configuration management with YAML-based customization, fallback to defaults, and type-safe value handling.

---

### 2. Data Structures Module
**Lines:** `app.py:374-430`

#### Global Data Structures

**Modality Data Structure:**
```python
modality_data = {
    'ct': {
        'default_file_path': 'uploads/SBZ_CT.xlsx',
        'scheduled_file_path': 'uploads/SBZ_CT_scheduled.xlsx',
        'working_hours_df': DataFrame,
        'draw_counts': {},
        'skill_counts': {'Normal': {}, 'Notfall': {}, ...},
        'WeightedCounts': {},
        'worker_modifiers': {},
        'last_reset_date': None,
        'info_texts': {}
    },
    # ... mr, xray
}
```

**Global Worker Data:**
```python
global_worker_data = {
    'worker_ids': {},  # canonical ID mapping
    'weighted_counts_per_mod': {
        'ct': {},  # weighted assignments
        'mr': {},
        'xray': {}
    },
    'assignments_per_mod': {
        'ct': {},  # raw counts
        'mr': {},
        'xray': {}
    },
    'last_reset_date': None
}
```

#### Purpose
Central storage for all runtime data, worker assignments, and cross-modality tracking.

---

### 3. Worker ID Management Module
**Lines:** `app.py:433-500`

#### Functions
- `get_canonical_worker_id(worker_name)` (433-448)
  - Normalizes worker names to canonical IDs
  - Handles name variations

- `get_global_weighted_count(canonical_id)` (451-459)
  - Sums weighted assignments across all modalities
  - Returns total workload

- `update_global_assignment(person, role, modality)` (462-489)
  - Calculates weighted assignment value
  - Updates global tracking dictionaries
  - Applies skill weights, modality factors, worker modifiers

- `reset_global_data()` (492-500)
  - Clears all global counters
  - Resets worker ID mappings

#### Purpose
Manages worker identity across modalities and tracks global workload distribution.

---

### 4. Excel File Management Module
**Lines:** `app.py:503-715`

#### Components

**DataFrame Initialization:**
- `initialize_data(file_path, modality)` (503-649)
  - Loads Excel file
  - Validates structure
  - Processes worker data
  - Initializes counters

- `attempt_initialize_data(file_path, modality, remove_on_failure)` (652-693)
  - Wrapper with error handling
  - Calls `quarantine_excel()` on failure

**File Quarantine:**
- `quarantine_excel(file_path, reason)` (696-715)
  - Moves corrupted files to `uploads/invalid/`
  - Timestamps quarantined files

#### Purpose
Handles all Excel file operations including loading, validation, and error recovery.

---

### 5. Worker Selection Module
**Lines:** `app.py:718-1322`

#### Sub-modules

**A. Load Calculation** (748-827)
- `_get_effective_assignment_load()` - Combine local + global load
- `_apply_minimum_balancer()` - Prioritize underutilized workers
- `_should_balance_via_fallback()` - Detect imbalance

**B. Skill Fallback** (830-909)
- `_attempt_column_selection()` - Try specific skill
- `_try_configured_fallback()` - Walk fallback chain
- `get_active_df_for_role()` - Map role to skills

**C. Modality Selection** (911-971)
- `_select_worker_for_modality()` - Core selection algorithm
- Filters by time, skill, balancing
- Calculates weighted ratio

**D. Main Selection Entry** (974-987)
- `get_next_available_worker()` - Routes to strategy

**E. Strategy Implementations**
- **Path 1:** `_get_worker_skill_priority()` (990-1049)
- **Path 2:** `_get_worker_modality_priority()` (1052-1178)
- **Path 3:** `_get_worker_pool_priority()` (1181-1322)

#### Purpose
Implements all worker selection logic with three configurable strategies and comprehensive balancing.

---

### 6. Daily Reset Module
**Lines:** `app.py:1325-1387`

#### Function
- `check_and_perform_daily_reset()` (1325-1387)
  - Triggered on every request via `@app.before_request`
  - Checks if new day + time >= 7:30
  - Resets counters for all modalities
  - Loads scheduled files
  - Moves files to backup
  - Updates global reset date

#### Purpose
Automates daily schedule transitions at 7:30 AM.

---

### 7. Assignment Logic Module
**Lines:** `app.py:1390-1419`

#### Function
- `_assign_worker(modality, role, allow_fallback)` (1390-1419)
  - Main assignment orchestrator
  - Validates modality
  - Gets current Berlin time
  - Calls selection strategy
  - Updates counters
  - Returns assignment result

#### Purpose
Coordinates worker assignment process from request to response.

---

### 8. Backup & Persistence Module
**Lines:** `app.py:1422-1451`

#### Function
- `backup_dataframe(modality)` (1422-1451)
  - Creates live backup Excel file
  - Excludes runtime columns
  - Includes info texts (Tabelle2)
  - Handles errors gracefully

#### Purpose
Maintains crash recovery backups after every data modification.

---

### 9. Application Initialization Module
**Lines:** `app.py:1454-1524`

#### Function
- `initialize_app()` (1454-1524)
  - Creates upload directories
  - Loads all modality files
  - Initializes global data
  - Logs startup status

#### Purpose
Bootstraps application on startup with proper error handling.

---

### 10. Web Routes Module
**Lines:** `app.py:1527-1896`

#### Components

**Authentication:**
- `login_required()` decorator (1527-1535)
- `/login` (1538-1558)
- `/logout` (1561-1565)

**Pages:**
- `/` - Main dashboard (1570-1580)
- `/upload` - File upload page (1624-1626)
- `/entries/<modality>` - View entries (1629-1639)
- `/admin_view` - Admin overview (1673-1696)

**API Endpoints:**
- `/api/<modality>/<role>` - Assignment (1699-1704)
- `/api/<modality>/<role>/strict` - Strict assignment (1707-1712)
- `/api/update_entry/<modality>/<int:index>` - Edit entry (1738-1803)
- `/api/delete_entry/<modality>/<int:index>` - Delete entry (1806-1844)
- `/api/statistics` - Get stats (1849-1896)

**File Upload:**
- `/upload_file` - Handle uploads (1583-1622)

#### Purpose
Provides HTTP interface for all system functionality.

---

## 🔗 Module Dependencies

```
┌──────────────────────────────────────────────────────────┐
│              Configuration Management                     │
│              (Loads config.yaml)                         │
└────────────────────┬─────────────────────────────────────┘
                     │ Provides settings
                     ▼
┌──────────────────────────────────────────────────────────┐
│              Data Structures                              │
│              (modality_data, global_worker_data)         │
└────────────────────┬─────────────────────────────────────┘
                     │ Used by
                     ▼
┌──────────────────────────────────────────────────────────┐
│         Worker ID Management                              │
│         (Canonical IDs, Global Tracking)                 │
└────────────────────┬─────────────────────────────────────┘
                     │ Used by
                     ▼
┌──────────────────────────────────────────────────────────┐
│         Excel File Management                             │
│         (Load, Validate, Quarantine)                     │
└────────────────────┬─────────────────────────────────────┘
                     │ Populates
                     ▼
┌──────────────────────────────────────────────────────────┐
│         Worker Selection Module                           │
│         (3 Paths + Balancing Logic)                      │
└────────────────────┬─────────────────────────────────────┘
                     │ Used by
                     ▼
┌──────────────────────────────────────────────────────────┐
│         Assignment Logic                                  │
│         (Orchestrate Selection + Update)                 │
└────────────────────┬─────────────────────────────────────┘
                     │ Called by
                     ▼
┌──────────────────────────────────────────────────────────┐
│              Web Routes                                   │
│              (API Endpoints + Pages)                     │
└──────────────────────────────────────────────────────────┘

         ┌─────────────────────────────────────┐
         │  Daily Reset Module                  │
         │  (Triggered by @before_request)     │
         │  Updates: Data Structures Module    │
         └─────────────────────────────────────┘

         ┌─────────────────────────────────────┐
         │  Backup & Persistence Module         │
         │  (Triggered after modifications)    │
         │  Creates: Live backup Excel files   │
         └─────────────────────────────────────┘
```

---

## 🎨 Design Patterns

### 1. **Strategy Pattern**
**Location:** Worker Selection Module

Three interchangeable selection strategies (`skill_priority`, `modality_priority`, `pool_priority`) with common interface.

### 2. **Fallback Chain Pattern**
**Location:** Skill Fallback Module

Configurable fallback sequences with support for parallel groups.

### 3. **Template Method Pattern**
**Location:** `_select_worker_for_modality()`

Common selection algorithm with pluggable balancing and filtering steps.

### 4. **Singleton Pattern**
**Location:** Data Structures Module

Global data structures shared across all requests (with thread lock for assignments).

### 5. **Decorator Pattern**
**Location:** Authentication

`@login_required` decorator wraps route handlers.

---

## 📊 Module Interaction Flow

### Assignment Request Flow
```
1. User → Web Routes → `/api/ct/privat`
2. Web Routes → Assignment Logic → `_assign_worker()`
3. Assignment Logic → Daily Reset → Check if reset needed
4. Assignment Logic → Worker Selection → `get_next_available_worker()`
5. Worker Selection → Strategy (e.g., skill_priority)
6. Strategy → Modality Selection → `_select_worker_for_modality()`
7. Modality Selection → Load Calculation → Get effective load
8. Modality Selection → Minimum Balancer → Filter candidates
9. Modality Selection → Calculate ratios → Pick best
10. Worker Selection → Return result
11. Assignment Logic → Update Counters → Worker ID Management
12. Assignment Logic → Backup → Persistence Module
13. Web Routes → Return JSON response
```

---

## 🔧 Configuration Files

### config.yaml Structure
```yaml
admin_password: "..."

modalities:
  ct:
    label: "CT"
    nav_color: "#1a5276"
    factor: 1.0
  # ... mr, xray

skills:
  Normal:
    label: "Normal"
    weight: 1.0
    fallback: []
  Notfall:
    label: "Notfall"
    weight: 1.1
    fallback: ["Normal"]
  # ... other skills

balancer:
  enabled: true
  min_assignments_per_skill: 5
  imbalance_threshold_pct: 30
  allow_fallback_on_imbalance: true
  fallback_strategy: skill_priority
  fallback_chain:
    Normal: []
    Notfall: ["Normal"]
    Privat: ["Notfall", ["Normal", "Herz"]]
    # ... other skills

modality_fallbacks:
  ct: ["mr"]
  mr: ["ct"]
  # ... optional modality fallbacks
```

---

## 📈 Code Metrics

**Total Lines:** ~1,900 lines
**Main Modules:** 10 distinct functional modules
**Selection Strategies:** 3 (skill_priority, modality_priority, pool_priority)
**API Endpoints:** 10+ routes
**Configuration Options:** 20+ settings in config.yaml

---

## 🎯 Key Architectural Benefits

### 1. **Modularity**
Each module has clear responsibilities and minimal coupling.

### 2. **Configurability**
YAML-based configuration allows customization without code changes.

### 3. **Extensibility**
New selection strategies can be added without modifying existing code.

### 4. **Resilience**
Multiple fallback mechanisms and error handling at every level.

### 5. **Observability**
Comprehensive logging throughout all modules.

### 6. **Fairness**
Multiple balancing mechanisms ensure equitable work distribution.

---

## 🔍 Module Testing Recommendations

### Configuration Management
- Test YAML loading with missing files
- Test default value fallbacks
- Test invalid configuration values

### Worker Selection
- Test all 3 selection strategies
- Test fallback chains
- Test imbalance detection
- Test minimum balancer

### Excel File Management
- Test corrupted file quarantine
- Test scheduled file loading
- Test backup creation
- Test startup initialization

### Daily Reset
- Test reset at 7:30 trigger
- Test counter clearing
- Test file movements
- Test multiple modalities

### Assignment Logic
- Test strict vs. normal mode
- Test cross-modality tracking
- Test weighted calculations
- Test concurrent requests (thread safety)

---

## 📚 Related Documentation

- **Testing Guide:** `TESTING_GUIDE.md`
- **Configuration Reference:** `config.yaml`
- **API Documentation:** See Web Routes Module section
- **README:** `README.md`

---

**STATUS:** ✅ System architecture is well-modularized with clear separation of concerns
**MAINTAINABILITY:** 🟢 HIGH - Each module can be tested and modified independently
**EXTENSIBILITY:** 🟢 HIGH - New features can be added through configuration or new modules
