# RadIMO SBZ - Complete System Analysis

## Table of Contents
1. [Excel File Handling - Complete Analysis](#excel-file-handling---complete-analysis)
2. [Distribution Logic & Balancing Report](#distribution-logic--balancing-report)
3. [Modular Architecture Report](#modular-architecture-report)

---

# Excel File Handling - Complete Analysis

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
**"Build complete pool of ALL (skill, modality) combinations and pick globally best worker"**

### Search Order
```
Build Cartesian product: all skills × all modalities
Evaluate EVERY combination simultaneously
Score each using weighted_ratio
Return single globally-best candidate
```

### How It Works
1. Creates Cartesian product of all valid (skill, modality) combinations
2. Evaluates EVERY combination at once
3. Uses `weighted_ratio` to score each combination
4. Returns single globally-best candidate from entire pool
5. Logs pool size and selection details

### Example Flow
**Request:** CT / Privat

```
Build pool of ALL possibilities:
  CT × Privat
  CT × Notfall
  CT × Normal
  MR × Privat
  MR × Notfall
  MR × Normal
  XRAY × Privat
  XRAY × Notfall
  XRAY × Normal

Evaluate all 9 combinations
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
    # Build skill fallback sequence
    skill_sequence = _build_skill_fallback_sequence(role, modality, allow_fallback)

    # Build modality search order
    modality_sequence = [modality] + get_modality_fallbacks(modality)

    # Build COMPLETE pool (Cartesian product)
    pool = []
    for skill in skill_sequence:
        for mod in modality_sequence:
            result = _select_worker_for_modality(current_dt, skill, mod, ...)
            if result:
                pool.append({
                    'worker': result['person'],
                    'skill': skill,
                    'modality': mod,
                    'ratio': result['ratio'],
                    'source': result['source']
                })

    # Pick globally best
    if pool:
        best = min(pool, key=lambda x: x['ratio'])
        return best

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

### 2. Minimum Balancer
**Function:** `_apply_minimum_balancer()`
**Location:** `app.py:776-795`

Ensures fair distribution by prioritizing underutilized workers:

```python
def _apply_minimum_balancer(filtered_df, column, modality):
    if not BALANCER_SETTINGS.get('enabled', True):
        return filtered_df

    min_required = BALANCER_SETTINGS.get('min_assignments_per_skill', 5)

    # Prioritize workers below minimum
    prioritized = filtered_df[
        filtered_df['PPL'].apply(
            lambda worker: _get_effective_assignment_load(worker, column, modality) < min_required
        )
    ]

    return prioritized if not prioritized.empty else filtered_df
```

**Configuration:** `config.yaml:113`
```yaml
min_assignments_per_skill: 5  # Workers must reach this before others get more
```

---

### 3. Imbalance Detection
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
**Location:** `app.py:864-909`

Maps request role to skill column and applies fallback strategy:

```python
def get_active_df_for_role(current_dt, role, modality, allow_fallback):
    # Role mapping
    role_map = {
        'normal': 'Normal',
        'notfall': 'Notfall',
        'herz': 'Herz',
        'privat': 'Privat',
        'msk': 'Msk',
        'chest': 'Chest'
    }

    column = role_map.get(role.lower(), 'Normal')

    # Try primary column
    result = _attempt_column_selection(current_dt, column, modality, column)
    if result:
        return result

    # Try configured fallback chain
    return _try_configured_fallback(current_dt, column, modality, allow_fallback)
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
| **Search Pattern** | Modality → Skills | Skill → Modalities | All combinations |
| **Best For** | Modality expertise | Skill expertise | Maximum fairness |
| **Complexity** | Low | Medium | High |
| **Performance** | Fast | Medium | Slower (more checks) |
| **Fallback Logic** | Sequential | Parallel per skill | Global pool |
| **Cross-modality** | Last resort | Preferred | Equal weight |

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
Build pool:
  CT × Privat: Worker A (1.5)
  CT × Notfall: Worker D (1.1)
  CT × Normal: Worker E (0.9)
  MR × Privat: Worker B (1.2)
  MR × Notfall: Worker F (1.0)
  MR × Normal: Worker G (0.8)
  XRAY × Privat: Worker C (2.0)
  XRAY × Notfall: Worker H (1.3)
  XRAY × Normal: Worker I (1.4)

Return: Worker G (lowest ratio across entire pool)
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
