# RadIMO Configuration Reference

Complete reference for `config.yaml` settings, synchronized with the current defaults.

---

## Overview

RadIMO uses a single `config.yaml` file for all configuration. Changes require application restart unless otherwise noted.

```yaml
# Main sections
admin_password: "..."           # Admin login
skill_roster_auto_import: true # Auto-add new workers to roster JSON
modalities: {...}               # CT, MR, XRAY, Mammo definitions
skills: {...}                   # Skill definitions, UI ordering
...
```

---

## Global Settings

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `admin_password` | string | `change_pw_for_live` | Password for all admin routes |
| `skill_roster_auto_import` | boolean | `true` | When loading CSV, auto-add missing workers to the Skill Matrix JSON |

---

## Scheduler Settings

Configure timings for automated background tasks.

```yaml
scheduler:
  daily_reset_time: "07:30"  # Time when Staked -> Live happens automatically
  auto_preload_time: 14      # Hour (0-23) when tomorrow's CSV is auto-loaded into staging
```

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `daily_reset_time` | string | `07:30` | Time format (HH:MM). Shifts the "Live" data to the new date. |
| `auto_preload_time` | integer | `14` | 24h format hour. Triggers automatic fetching of the next workday from the Master CSV. |

---

## Modalities

Define available modalities with display and optional visibility filters.

```yaml
modalities:
  ct:
    label: CT              # Display name
    nav_color: '#1a5276'   # Navigation button color
    hover_color: '#153f5b' # Button hover color
    background_color: '#e6f2fa'  # Page background
  mr:
    label: MR
    nav_color: '#777777'
    hover_color: '#555555'
    background_color: '#f9f9f9'
  xray:
    label: XRAY
    nav_color: '#239b56'
    hover_color: '#1d7a48'
    background_color: '#e0f2e9'
    hidden_skills: [gyn, aou, cvt]  # MDH is shown again on xray
  mammo:
    label: Mammo
    nav_color: '#e91e63'
    hover_color: '#c2185b'
    background_color: '#fce4ec'
    valid_skills: [notfall, privat, gyn]  # Optional whitelist
    # hidden_skills: [gyn, aou, cvt] # Optional blacklist
```

**Visibility filters (optional):**
- `valid_skills`: only show these skills for the modality
- `hidden_skills`: hide these skills for the modality

---

## Skills

Define skills with UI styling and ordering.

Use `tooltip` for a longer hover text when the visible button label is short
or abbreviated. If omitted, the button falls back to `label`.

```yaml
skills:
  notfall:
    label: Notfall
    button_color: '#dc3545'
    text_color: '#ffffff'
    special: false
    display_order: 0
    slug: notfall

  privat:
    label: Privat
    button_color: '#ffc107'
    text_color: '#333333'
    special: false
    display_order: 1
    slug: privat

  gyn:
    label: Gyn
    button_color: '#e91e63'
    text_color: '#ffffff'
    special: true
    # valid_modalities: [mammo, mr]  # Optional: only show on these modalities
    # hidden_modalities: [xray]      # Optional: hide on these modalities
    display_order: 2
    slug: gyn

  paed:
    label: Päd
    button_color: '#4caf50'
    text_color: '#ffffff'
    special: true
    display_order: 3
    slug: paed

  mdh:
    label: MDH
    tooltip: Muskel-Skelett / Hals / Derma
    button_color: '#9c27b0'
    text_color: '#ffffff'
    special: true
    display_order: 4
    slug: mdh

  aou:
    label: AOU
    tooltip: Abdomen / Uro / Onko
    button_color: '#00bcd4'
    text_color: '#ffffff'
    special: true
    display_order: 5
    slug: aou

  cvt:
    label: CVT
    tooltip: Cardio / Vask / Thorax
    button_color: '#28a745'
    text_color: '#ffffff'
    special: true
    display_order: 1
    slug: cvt

  mdh:
    label: MDH
    button_color: '#607d8b'
    text_color: '#ffffff'
    special: true
    display_order: 3
    slug: mdh
```

**Special flag:**
- `special: true` marks subspecialty buttons with distinct styling (larger buttons).
**Tooltip:**
- `tooltip` is optional and is used as hover text / accessible label for short button names.
**Key format:**
- Skill keys are URL-safe slugs (lowercase, no spaces, no `/`, no umlauts).
- Use `label` for the human-readable display name (e.g., `label: "MDH"`).

---

## Button Weight Matrix (Normal + Strict)

Manage per-button weights in the **Weight Matrix** admin page (`/button-weights`).
Weights are stored in `data/button_weights.json` (with automatic backup rotation) instead of `config.yaml`.

**Defaults:**
- Normal weights default to `1.0` when blank
- Strict weights fall back to the normal value when blank

**Important behavior:**
- Normal dashboard buttons use normal weights.
- `no_overflow` only changes routing to specialist-only; it does not switch to strict weights.
- Special tasks with `allow_overflow: false` also keep using special normal weights.
- Strict weights are used only by the explicit `/strict` path, including the visible `*` button when enabled.

---

## No Overflow (Strict Mode) Combinations

Disable overflow to generalists for specific skill×modality combinations. When a combo is listed here, the normal dashboard button runs in specialist-only mode - only specialists (skill=1 or 'w') will be assigned, never generalists (skill=0).

```yaml
no_overflow:
  - cvt_ct    # Cardiac CT - specialists only
  - cvt_mr    # Cardiac MR - specialists only
  - gyn_mr         # Gyn MR - specialists only
  - notfall_ct     # Notfall CT - specialists only, no strict button
  - notfall_mr     # Notfall MR - specialists only, no strict button
  - notfall_xray   # Notfall Xray - specialists only, no strict button
  - mdh_xray   # Xray MDH runs strict/no-overflow only
```

**Format:** `Skill_Modality` (same as `skill_overrides` in shift rules)

The config loader also accepts the reversed alias `Modality_Skill` and normalizes
it to canonical `Skill_Modality` internally. For example, `xray_notfall` becomes
`notfall_xray`.

**How it works:**
1. When assignment is requested for a listed combo, `allow_overflow` is forced to `false`
2. Only workers with skill=1 or 'w' are eligible
3. Weight selection remains in normal mode for that button
4. Strict weights are only used when `/strict` is called explicitly

**Use cases:**
- Specialized procedures requiring trained specialists (cardiac imaging)
- Subspecialties where generalists lack expertise
- High-risk modalities where quality control is critical

## Strict Button Visibility

Control whether a visible `*` button is rendered next to specific dashboard buttons.
Buttons are hidden by default and must be enabled per button.

```yaml
strict_button_visibility:
  cvt_ct: true
  cvt_mr: true
  mdh_ct: true
  mdh_mr: true
  ct-herz_ct: true
  mr-herz_mr: true
```

**Supported keys:**
- Regular skill buttons use `skill_modality` keys such as `cvt_ct`
- Special task buttons use `taskslug_modality` keys such as `ct-herz_ct`

This is dashboard-level UI behavior, not per-worker behavior.

**Behavior:**
1. Visibility is UI-only; it does not change routing by itself
2. Clicking the visible `*` button calls `/api/{modality}/{role}/strict`
3. That explicit strict path uses both specialist-only routing and strict weights

## Specialist Fallback Routes (Group Merge, Specialist-Only)

Use this when one skill group should fall back to another specialist group
before any generic overflow.

```yaml
specialist_fallback_routes:
  aou: [mdh]
  mdh: [aou]
```

**Behavior:**
1. Request starts with primary `skill_modality` specialist pool (`1`/`w` only).
2. Fallback groups are checked only if the primary specialist pool is empty.
   Then the request runs as a virtual merged specialist route:
   primary + fallback in the same modality.
3. In normal mode (`allow_overflow=true`): if primary+fallback are empty, it enters regular overflow (skill=0 pool).
4. In strict mode (`allow_overflow=false`): only primary+fallback specialists are used (no generalist overflow).

**Best use case:**
- operationally merged teams (for example MDH merged with AOU)
- controlled cross-cover without opening to full generalist overflow

---

## Special Tasks

Special tasks are custom buttons that appear on dashboards alongside regular skill buttons. They route to an existing base skill but display separately, allowing you to track specific sub-workflows while using the same worker pool.

```yaml
special_tasks:
  - name: Abdonko_ct-seg
    label: CT Segmentation
    base_skill: aou
    modalities_dashboards: [ct]
    skill_dashboards: [aou]
    allow_overflow: false
    display_order: 999
```

### Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | Yes | Unique identifier (slug-friendly, no spaces) |
| `label` | string | No | Button display text (defaults to name) |
| `base_skill` | string | Yes | Which skill to use for worker selection and load balancing |
| `modalities_dashboards` | list | No | Which modality dashboards show this button (e.g., `[ct, mr]`) |
| `skill_dashboards` | list | No | Which skill dashboards show this button (e.g., `[aou]`) |
| `allow_overflow` | boolean | No | Whether generalists (skill=0) can be assigned (default: true) |
| `display_order` | integer | No | Button ordering (default: 999, appears after regular skills) |
| `tooltip` | string | No | Hover text / accessible full name (defaults to `label`) |

### How It Works

1. **Configuration**: Define special tasks in `config.yaml` under `special_tasks`
2. **Dashboard rendering**: Buttons appear on specified modality/skill dashboards with the base skill's colors
3. **Assignment**: Clicking the button calls `/api/{modality}/{task_slug}` which resolves to the base_skill
4. **Load balancing**: Assignments are balanced using the base skill's worker pool
5. **Weight configuration**: Configure weights via the Weight Matrix admin page (`/button-weights`)
6. **Overflow behavior**: `allow_overflow: false` disables generalist overflow but still uses special normal weights unless `/strict` is called explicitly

### Weight Configuration

Special task weights are managed in the **Weight Matrix** admin page (`/button-weights`), not in `config.yaml`.

- Weights are stored in `data/button_weights.json` under `special.normal` and `special.strict`
- The weight key format is `{task_slug}_{modality}` (e.g., `abdonko_ct-seg_ct`)
- Default weight is `1.0` - higher values increase workload contribution
- Strict weights fall back to normal weights when not set
- Regular special-task clicks use `special.normal`, even when `allow_overflow: false`
- The `special.strict` table is used only by the explicit strict path

### Example Use Cases

**CT Segmentation tracking:**
```yaml
- name: ct-seg
  label: CT Segmentation
  base_skill: aou
  modalities_dashboards: [ct]
  allow_overflow: false  # Only specialists
```

**Multi-modality subspecialty:**
```yaml
- name: cardiac-mri
  label: Cardiac MRI
  base_skill: cvt
  modalities_dashboards: [mr]
  skill_dashboards: [cvt]
```

**Current xray setup in this repo:**
```yaml
- name: xray-normal
  label: Normal
  base_skill: cvt
  target_skill_modalities:
    - cvt_xray
  modalities_dashboards: [xray]
  allow_overflow: true
```

- The xray dashboard shows MDH again.
- `mdh_xray` runs in no-overflow mode without a visible strict `*` button.
- The NDOC roster/shifts use the `xray_notfall` alias, which normalizes to
  `notfall_xray`.

---

## Synthetic Shifts

Synthetic shifts are recurring config-defined worker rows that are injected into the day plan even when no matching Medweb entry exists. Use them for summary workers such as `GynDoc` or `NotfallDoc`.

```yaml
synthetic_shifts:
  - worker_name: GynDoc
    label: Gyn Summary
    weekdays: [workdays]
    times:
      default: "07:30-15:45"
    skill_overrides:
      gyn_ct: 1
      gyn_mr: 1
```

### Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `worker_name` | string | Yes | Display name stored in the schedule row and skill matrix |
| `label` | string | No | Task label shown in the schedule row |
| `weekdays` | list/string | No | German or English weekday names, `workdays`, or `all`; defaults to workdays |
| `times` | dict | No | Same structure as Medweb shift rules, defaults to `07:00-15:00` |
| `skill_overrides` | dict | Yes | Same `skill_overrides` structure used by Medweb shift rules |
| `modifier` | number | No | Shift load modifier for the injected row |
| `counts_for_hours` | boolean | No | Whether the synthetic row contributes to hours balancing |
| `gaps` | dict | No | Optional embedded gaps using the same format as shift-rule gaps |

### Behavior

1. Synthetic workers are auto-added to the skill matrix JSON with passive defaults if missing.
2. Shift-level `skill_overrides` activate the worker for the configured day.
3. Skill-matrix `-1` exclusions still win over synthetic shift activation.
4. Synthetic rows flow through timetable, prep pages, assignment routing, and worker-load views like ordinary rows.

---

## Skill Value Colors

How skill values appear in the prep page table.

```yaml
skill_value_colors:
  active:     # skill = 1 (primary assignment)
    color: '#28a745'
  passive:    # skill = 0 (fallback only)
    color: '#6c757d'
  excluded:   # skill = -1 (never assign)
    color: '#dc3545'
  weighted:   # skill = 'w' (assisted/weighted)
    color: '#17a2b8'
```

---

## Skill Value Hierarchy & Overwrite Logic

This section documents how skill values (`-1`, `0`, `1`, `w`) are resolved across the system.

### Skill Value Meanings

| Value | Name | Meaning | Balancer Behavior |
|-------|------|---------|-------------------|
| `-1` | **Excluded** | Worker cannot perform this skill/modality | Filtered out entirely - never receives work |
| `0` | **Generalist** | Worker CAN do this work as backup | Fallback pool - only receives work when specialists overloaded |
| `1` | **Specialist** | Worker is trained for this work | Priority assignment, uses shift load modifier |
| `w` | **Weighted** | Worker is in training/assisted | Priority assignment, uses shift load modifier + W modifier stream |

### Value Sources (Priority Order)

1. **Skill Roster** (`worker_skill_roster.json`) - baseline per-worker skill settings
2. **CSV Mapping Rules** (`skill_overrides` in config) - shift-specific overrides
3. **Prep Page Edits** - manual daily adjustments

### Overwrite Rules During CSV Loading

When CSV mapping rules apply `skill_overrides` to a worker's roster values:

| Roster Value | CSV Override | Result | Explanation |
|--------------|--------------|--------|-------------|
| `-1` | any | `-1` | **Roster `-1` always wins** - hard exclusions cannot be overridden |
| `1` | any | CSV value | Normal override |
| `0` | any | CSV value | Normal override |
| `w` | `1` or `w` | `w` | Weighted baseline stays weighted when explicitly assigned |
| `w` | `0` or `-1` | `-1` | Weighted baseline is excluded unless the shift explicitly assigns it |

**Current roster model:** the roster baseline normally uses `0`, `-1`, and optionally `w`. Full active day-state still comes from shift rows or live/prep edits.

### Overwrite Rules During Prep/UI Edits

Manual edits in the prep page can change schedule row values directly:

- No restrictions - allows daily flexibility
- Can change `-1` → `w`/`1` (e.g., adding someone new to a team)
- Can change `w` → `1` (promoting from training to full)
- Changes persist only for that day's schedule

**Roster re-apply on load:** When schedules are reloaded (live/staged JSON),
row values of `1` or `w` reactivate against roster/live `0`, while row value `0`
stays passive. Roster/live `-1` remains blocked.

### Modifiers

The system uses two modifier streams:

#### Where to configure each weight stream

| Weight stream | Page |
|---|---|
| Shift load modifier | `/prep-today` and `/prep-tomorrow` |
| W modifier (`w` only) | `/skill-roster` |
| Skill×modality base matrix | `/button-weights` |

#### Shift Load Modifier (applies to ALL assignments)

The schedule row `Modifier` is a shift-level load multiplier and applies to all assignments in that shift (`0`, `1`, and `w`).

| Value | Effect |
|-------|--------|
| `1.0` | Normal load (default) |
| `1.5` | ~33% less load per assignment |
| `2.0` | ~50% less load per assignment |
| `0.8` | ~25% more load per assignment |

Set this in `/prep-today` or `/prep-tomorrow` as **Shift Load Modifier**.

#### W Modifier (additional stream for `w` only)

For weighted (`w`) assignments, an additional W stream is applied:

```
effective_w_modifier = roster_w_modifier × default_w_modifier
```

| Source | When Used |
|--------|-----------|
| **Roster W Modifier** | Worker-level W stream from roster (`modifier`), or `1.0` if unset |
| **Default W Modifier** | Global baseline W stream (`balancer.default_w_modifier`) |

Set the worker-level part in `/skill-roster` as **W Modifier**.

#### Combined Effect

For non-weighted (`0` or `1`) assignments:
```
weight_non_w = base_weight × (1.0 / shift_modifier)
```

For weighted (`w`) assignments:
```
weight_w = base_weight × (1.0 / shift_modifier) × (1.0 / effective_w_modifier)
```

Compact form:
```
weight = base_weight × (1.0 / shift_modifier) × (is_w ? 1.0 / w_modifier : 1.0)
```

**Example:**
- `shift_modifier = 1.5`, `roster_w_modifier = 2.0`, `default_w_modifier = 0.5`
- Non-w assignment: `base × (1/1.5) = base × 0.67`
- W assignment: `base × (1/1.5) × (1/(2.0×0.5)) = base × 0.67`

---

## UI Colors

Top-level UI theme settings.

```yaml
ui_colors:
  today_tab: '#28a745'        # Green for "Change Today"
  tomorrow_tab: '#ffc107'     # Yellow for "Prep Tomorrow"
  success: '#28a745'
  error: '#dc3545'
```

---

## Balancer Settings

Control load balancing behavior and hours counting.

```yaml
balancer:
  enabled: true
  min_assignments_per_skill: 5    # Minimum weighted assignments gate for specialists
  warm_start_release_mode: either # either|both for warm-start overflow release
  imbalance_threshold_pct: 20     # Trigger overflow at 20% imbalance
  disable_overflow_at_shift_end_minutes: 30  # Don't assign overflow in last X minutes

  # Hours counting for workload calculation
  hours_counting:
    shift_default: true   # type: "shift" entries count towards hours (default)
    gap_default: false    # type: "gap" entries don't count towards hours (default)

  # Exclusion-based routing configuration
  # Define which workers to EXCLUDE when requesting each skill
  # Workers with excluded_skill=1 won't receive work for this skill
  # Format (shortcut style - supports skill, modality, or skill_mod combos):
  #   skill: []                    # No exclusions
  #   skill: [skill1]              # Exclude workers with skill1=1 (all modalities)
  #   skill: [skill1, skill2]      # Exclude workers with skill1=1 OR skill2=1
  #   skill_mod: [skill1_mod]      # Exclude specific combo (e.g., cvt_ct: [mdh_ct])
  #   mod: [skill1]                # Modality-wide (all *_mod skills exclude skill1)
  exclude_skills:
    notfall: []      # No exclusions
    privat: []
    gyn: []
    paed: []
    mdh: []
    aou: []
    cvt: []     # Example: cvt: [mdh] means CVT work excludes MDH specialists
```

### Specialist-First Assignment with Pooled Worker Overflow

The system prioritizes specialists while using pooled workers (skill=0) as backup capacity within each modality:

**Assignment Strategy:**

1. **Filter workers in requested modality:**
   - Include workers with skill≥0 (excludes skill=-1)
   - Apply shift end buffer for overflow pool (`disable_overflow_at_shift_end_minutes`)
   - Apply warm-start release policy using shift-start minutes + min-count
   - Apply exclusion rules (e.g., notfall_ct team won't get mammo_gyn)

2. **Split into pools:**
   - **Specialists:** skill=1 or 'w' (trained for this work)
   - **Generalists:** skill=0 (trained in modality, can help when needed)

3. **Minimum balancer (fair distribution among specialists):**
   - Uses `min_assignments_per_skill` as a warm-start gate for specialists
   - Prevents strange effects at start of day

3a. **Warm-start release policy (time + count):**
   - Time gate from `disable_overflow_at_shift_start_minutes`
   - Count gate from `min_assignments_per_skill`
   - `warm_start_release_mode: either` -> overflow can start when time OR count gate is satisfied
   - `warm_start_release_mode: both` -> overflow starts only when time AND count are satisfied

4. **Specialist-first selection with imbalance overflow:**
   - Calculate workload ratio for each worker (weighted_count / hours_worked)
   - If hours_worked is 0, ratios are treated as 0 when weighted_count is 0, or very high when weighted_count exists
   - Compare min_specialist_ratio vs min_generalist_ratio
   - If imbalance ≥ threshold% (normalized against the higher pool average): overflow to generalist with lowest ratio
   - Otherwise: assign to specialist with lowest ratio

5. **Fallback without exclusions:**
   - If no workers available after exclusions, retry without exclusion filters
   - Maintains specialist-first logic

**Configuration:**
```yaml
balancer:
  min_assignments_per_skill: 3             # Specialist count gate
  warm_start_release_mode: either          # Release overflow when time OR count is ready
  imbalance_threshold_pct: 20              # Overflow when specialists 20%+ more loaded than generalists
  disable_overflow_at_shift_start_minutes: 15  # Don't assign overflow in first 15min of shift
  disable_overflow_at_shift_end_minutes: 30    # Don't assign overflow in last 30min of shift
  exclude_skills:
    cvt: [mdh]  # MDH specialists won't get CVT work unless no one else available
```

### Warm-Start Release Modes

`min_assignments_per_skill` can be combined with shift-start minutes:

- `warm_start_release_mode: either`
  Overflow unlocks when either condition is met:
  time passed OR specialist minimum reached.
- `warm_start_release_mode: both`
  Overflow unlocks only when both conditions are met:
  time passed AND specialist minimum reached.

---

## Vendor Mappings (Medweb CSV)

Map activity descriptions from vendor CSV files to shifts and gaps. The current implementation uses **vendor_mappings** with a unified structure where times are embedded directly in each rule.

```yaml
vendor_mappings:
  medweb:
    # Column name mappings for this vendor
    columns:
      date: "Datum"
      activity: "Beschreibung der Aktivität"
      employee_name: "Name des Mitarbeiters"
      employee_code: "Code des Mitarbeiters"
      day_part: "Tageszeit"  # Optional: VM/NM import column for rule filters

    # Rules for mapping activities to shifts/gaps
    # Rules are evaluated in order; first match wins
    rules:
    # ===========================================
    # SHIFTS - Work assignments with times and skill_overrides
    # ===========================================

    # CT Shifts
    - match: "CT Spätdienst"
      type: "shift"
      times:
        default: "13:00-21:00"
        Freitag: "13:00-19:00"
      skill_overrides:
        notfall_ct: 1
        privat_ct: 1
        mdh_ct: 0
        aou_ct: 0
        cvt_ct: 0
        gyn_ct: 0
        paed_ct: 0

    - match: "CT Assistent"
      type: "shift"
      times:
        default: "07:00-15:00"
        Freitag: "07:00-13:00"
      skill_overrides:
        notfall_ct: 1
        privat_ct: 1
        mdh_ct: 0

    # Weighted entry (beginner/assisted worker)
    - match: "MR Assistent 1. Monat"
      type: "shift"
      times:
        default: "07:00-15:00"
        Freitag: "07:00-13:00"
      modifier: 0.3  # Very low-yield shift (~30% capacity, e.g., protected non-RadIMO time)
      skill_overrides:
        notfall_mr: w
        privat_mr: 0

    # Multi-modality team
    - match: "MDH Team"
      type: "shift"
      times:
        default: "07:00-15:00"
        Freitag: "07:00-13:00"
      skill_overrides:
        mdh_ct: 1
        mdh_mr: 1
        mdh_xray: 1

    # Administrative shift that doesn't count toward load balancing
    - match: "Cortex Aufklärung"
      type: "shift"
      times:
        default: "07:00-15:00"
        Freitag: "07:00-13:00"
      label: "Aufklärung"
      counts_for_hours: false  # Administrative task
      skill_overrides:
        notfall_ct: 0  # Minimal skill, just to have a modality

    # ===========================================
    # GAPS - Time exclusions (worker unavailable)
    # ===========================================

    - match: "Kopf-Hals-Board"
      type: "gap"
      times:
        Montag:
          - "15:30-17:00"
      skill_overrides:
        all: -1

    - match: "Board"
      type: "gap"
      times:
        Dienstag:
          - "15:00-17:00"
        Mittwoch:
          - "10:00-12:00"
        Donnerstag:
          - "14:00-16:00"
      skill_overrides:
        all: -1
```

### Rule Matching

**First match wins.** Order rules from specific to general.

### Skill Override Shortcuts

The `skill_overrides` field supports shortcuts:
- `all: -1` → all Skill×Modality combinations = -1
- `mdh: 1` → all mdh_* combinations = 1 (mdh_ct, mdh_mr, etc.)
- `ct: 1` → all *_ct combinations = 1 (notfall_ct, mdh_ct, etc.)
- `xray: -1` → all *_xray combinations = -1

### Weighted/Assisted Workers

Use `skill_overrides: {Skill_mod: w}` plus a `modifier` (0.3–1.5):
```yaml
- match: "MDH Anfänger"
  modifier: 0.3  # Very low-yield shift (~30% capacity, e.g., protected non-RadIMO time)
  skill_overrides:
    mdh_ct: w
    mdh_xray: w
```

### Hours Counting

- **Shifts** count toward workload unless `counts_for_hours: false`
- **Gaps** do NOT count toward workload (defaults from `balancer.hours_counting`)

### Day-Specific Times

Times support day-specific overrides:
- `default`: Monday-Thursday (or all days if no day-specific override)
- `Montag`, `Dienstag`, `Mittwoch`, `Donnerstag`, `Freitag`: Day overrides
- English weekday keys (`monday` ... `friday`) are also accepted for legacy configs

Gaps support multiple time blocks per day (arrays):
```yaml
times:
  Montag:
    - "10:00-11:00"
    - "14:00-15:00"
```

### VM/NM Day Parts

If the Medweb export includes a `Tageszeit` column, rules can also filter on it.
Use `day_part` for a single value or `day_parts` for multiple values:

```yaml
- match: "SBZ: Geräteassistenz"
  type: "gap"
  day_part: NM
  times:
    default: "15:45-20:00"

- match: "SBZ: Geräteassistenz"
  type: "gap"
  day_part: VM
  times:
    default: "07:30-15:45"
```

Rules without `day_part` keep the old wildcard behavior and match both VM and NM.

Matching is day-part aware:
- `day_part: VM` matches rows tagged `VM`
- `day_part: NM` matches rows tagged `NM`
- `day_parts: [VM, NM]` matches either `VM` or `NM`
- combined labels like `VM+NM`, `VM/NM`, `both`, `all`, or `any` are treated as `VM` for rule matching
- `NM`-only rows stay `NM` and therefore route to the late rule

### Segmented Rules

Use `segments` when one matched activity needs different times or different `skill_overrides`
within the same rule. Parent values act as defaults and each segment can override only the
parts that change.

```yaml
- match: "SBZ: Spätdienst"
  type: "shift"
  times:
    default: "11:30-20:00"   # optional top-level summary time for admin display
  skill_overrides:
    all: 0
    notfall: -1
  segments:
    - times:
        default: "11:30-15:45"
      skill_overrides:
        gyn: -1
    - times:
        default: "15:45-20:00"
      skill_overrides:
        gyn: 0
```

This produces two shift segments from one matched CSV activity. The same `segments` shape is
also supported for `type: "gap"` rules.

---

## Worker Skill Matrix

Defines Skill×Modality combinations for each worker. The worker roster is stored in `data/worker_skill_roster.json` and can be edited via the Skill Matrix admin page (`/skill-roster`).

**Format:** `"skill_modality": value` (e.g., `"mdh_ct": 0`)

Both `"skill_modality"` and `"modality_skill"` formats are accepted and normalized automatically.

**Automatic backups:** Changes are automatically backed up to `data/backups/` with rotation (keeps last 5 backups).

### Example (data/worker_skill_roster.json)

```json
{
  "AA": {
    "mdh_ct": 0,
    "mdh_mr": 0,
    "mdh_xray": 0,
    "mdh_mammo": 0,
    "notfall_ct": 0,
    "notfall_mr": 0,
    "notfall_xray": 0,
    "notfall_mammo": 0
  },
  "DEMO1": {
    "cvt_ct": 0,
    "cvt_mr": 0,
    "notfall_ct": 0,
    "notfall_mr": 0,
    "mdh_ct": -1,
    "mdh_mr": -1,
    "mdh_xray": -1
  },
  "DEMO_WEIGHTED": {
    "modifier": 2.0,
    "mdh_ct": 0,
    "mdh_xray": 0,
    "mdh_mr": 0
  }
}
```

### Value Legend

- `0` = **Passive** - fallback only (generalist pool)
- `-1` = **Hard exclude** - cannot be overridden by vendor CSV rules
- `modifier` = worker-level W stream, used only when a shift row assigns `w`

### Override Precedence

When combining roster values with vendor CSV `skill_overrides`:

1. **Worker roster** - baseline for all Skill×Modality pairs
2. **Vendor rule skill_overrides** - overrides only specified combinations
3. **Roster -1 (hard exclude)** - always wins, cannot be overridden

**Example:**
- Worker roster: `{"mdh_ct": 0, "mdh_mr": 0, "gyn_ct": 0, "gyn_mr": 0}`
- CSV rule assigns "Gyn Team" with `skill_overrides: {"gyn_ct": 1, "gyn_mr": 1}`
- Result: Gyn → 1, MDH stays 0 (passive baseline remains passive unless the shift assigns it)
- If roster had `"mdh_ct": -1`, it stays -1 (hard exclude wins)

---

## Complete Example

```yaml
admin_password: change_for_production
skill_roster_auto_import: true

modalities:
  ct:
    label: CT
    nav_color: '#1a5276'
  mr:
    label: MR
    nav_color: '#777777'
  xray:
    label: X-ray
    nav_color: '#239b56'
  mammo:
    label: Mammo
    nav_color: '#e91e63'
    valid_skills: [notfall, privat, gyn]

skills:
  notfall:
    label: Notfall
    display_order: 0
  privat:
    label: Privat
    display_order: 1
  cvt:
    label: CVT
    special: true
    display_order: 7

button_weights: (managed in data/button_weights.json)

balancer:
  enabled: true
  min_assignments_per_skill: 3
  imbalance_threshold_pct: 20
  disable_overflow_at_shift_start_minutes: 15
  disable_overflow_at_shift_end_minutes: 30
  hours_counting:
    shift_default: true
    gap_default: false
  exclude_skills:
    cvt: [mdh]
    notfall: []

vendor_mappings:
  medweb:
    columns:
      date: "Datum"
      activity: "Beschreibung der Aktivität"
      employee_name: "Name des Mitarbeiters"
      employee_code: "Code des Mitarbeiters"
    rules:
      - match: "CT Assistent"
        type: "shift"
        times:
          default: "07:00-15:00"
          Freitag: "07:00-13:00"
        skill_overrides:
          notfall_ct: 1
          privat_ct: 0
          cvt_ct: 0
      - match: "Kopf-Hals-Board"
        type: "gap"
        times:
          Montag:
            - "15:30-17:00"
        skill_overrides:
          all: -1
```

**Note:** Worker skill roster is stored in `worker_skill_roster.json` (not in config.yaml). See Worker Skill Matrix section above for format.

---

## Tips

1. **Adding new activity**: Add rule to `vendor_mappings.medweb.rules`, restart app
2. **Adjusting worker skills**: Use the Skill Matrix admin page (`/skill-roster`) or edit `worker_skill_roster.json` directly
3. **Fine-tuning balance**: Adjust the Weight Matrix (button weights)
4. **Testing config**: Run `python scripts/ops_check.py` to validate
5. **Generating rules from CSV**: Use `python scripts/prepare_config.py --input <csv>` to bootstrap vendor mapping rules
