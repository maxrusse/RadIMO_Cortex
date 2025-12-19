# RadIMO Configuration Reference

Complete reference for `config.yaml` settings, synchronized with the current defaults.

---

## Overview

RadIMO uses a single `config.yaml` file for all configuration. Changes require application restart unless otherwise noted.

```yaml
# Main sections
admin_password: "..."           # Admin login
modalities: {...}               # CT, MR, XRAY, Mammo definitions + visibility filters
skills: {...}                   # Skill definitions, weights, UI ordering
skill_modality_overrides: {...} # Custom weight overrides
skill_dashboard: {...}          # Skill selection UI guardrails
skill_value_colors: {...}       # How 1/0/-1/w appear in the prep table
ui_colors: {...}                # Flash + tab colors
balancer: {...}                 # Load balancing + hours counting
modality_fallbacks: {...}       # Cross-modality overflow
medweb_mapping: {...}           # CSV activity parsing (shifts + gaps)
shift_times: {...}              # Shift time definitions
worker_skill_roster: {...}      # Per-worker skill overrides
```

---

## Modalities

Define available modalities with display, weighting, and optional visibility filters.

```yaml
modalities:
  ct:
    label: CT              # Display name
    nav_color: '#1a5276'   # Navigation button color
    hover_color: '#153f5b' # Button hover color
    background_color: '#e6f2fa'  # Page background
    factor: 1.0            # Workload weight multiplier
  mr:
    label: MR
    nav_color: '#777777'
    hover_color: '#555555'
    background_color: '#f9f9f9'
    factor: 1.2            # MR work counts 20% more
  xray:
    label: XRAY
    nav_color: '#239b56'
    hover_color: '#1d7a48'
    background_color: '#e0f2e9'
    factor: 0.33           # XRAY work counts 1/3
  mammo:
    label: Mammo
    nav_color: '#e91e63'
    hover_color: '#c2185b'
    background_color: '#fce4ec'
    factor: 0.5            # Mammography counts half
    valid_skills: [Notfall, Privat, Gyn]  # Optional whitelist
    # hidden_skills: [MSK, Chest]         # Optional blacklist
```

**Factor**: Higher factor = work counts more toward weighted total. Use to balance effort across modalities.

**Visibility filters (optional):**
- `valid_skills`: only show these skills for the modality
- `hidden_skills`: hide these skills for the modality

---

## Skills

Define skills with weights, UI styling, and ordering.

```yaml
skills:
  Notfall:
    label: Notfall
    button_color: '#dc3545'
    text_color: '#ffffff'
    weight: 1.1
    optional: false
    special: false
    display_order: 0
    slug: notfall
    form_key: notfall

  Privat:
    label: Privat
    button_color: '#ffc107'
    text_color: '#333333'
    weight: 1.2
    optional: true
    special: false
    display_order: 1
    slug: privat
    form_key: privat

  Gyn:
    label: Gyn
    button_color: '#e91e63'
    text_color: '#ffffff'
    weight: 1.0
    optional: true
    special: true
    # valid_modalities: [mammo, mr]  # Optional: only show on these modalities
    # hidden_modalities: [xray]      # Optional: hide on these modalities
    display_order: 2
    slug: gyn
    form_key: gyn

  Päd:
    label: Päd
    button_color: '#4caf50'
    text_color: '#ffffff'
    weight: 1.0
    optional: true
    special: true
    display_order: 3
    slug: paed
    form_key: paed

  MSK:
    label: MSK
    button_color: '#9c27b0'
    text_color: '#ffffff'
    weight: 0.8
    optional: true
    special: true
    display_order: 4
    slug: msk
    form_key: msk

  Abdomen:
    label: Abdomen
    button_color: '#00bcd4'
    text_color: '#ffffff'
    weight: 1.0
    optional: true
    special: true
    display_order: 5
    slug: abdomen
    form_key: abdomen

  Chest:
    label: Chest
    button_color: '#ff9800'
    text_color: '#ffffff'
    weight: 0.8
    optional: true
    special: true
    display_order: 6
    slug: chest
    form_key: chest

  Cardvask:
    label: Cardvask
    button_color: '#28a745'
    text_color: '#ffffff'
    weight: 1.2
    optional: true
    special: true
    display_order: 7
    slug: cardvask
    form_key: cardvask

  Uro:
    label: Uro
    button_color: '#795548'
    text_color: '#ffffff'
    weight: 1.0
    optional: true
    special: true
    display_order: 8
    slug: uro
    form_key: uro
```

**Optional vs. special:**
- `optional: false` keeps the button visible even if no worker is active for the skill.
- `special: true` marks subspecialty buttons that can be hidden when no worker is available unless `optional: false`.

---

## Skill×Modality Weight Overrides

Override the default `skill_weight × modality_factor` calculation for specific combinations.

```yaml
skill_modality_overrides:
  mr:
    Cardvask: 1.8    # MR×Cardvask override
  # ct:
  #   Chest: 1.0     # Example override
```

**How it works:**
1. Check `skill_modality_overrides[modality][skill]` for explicit value
2. If not found, calculate: `skill_weight × modality_factor`

**Use cases:**
- Cardiac MR is more demanding → increase MR×Cardvask weight
- XRAY MSK is simpler → decrease XRAY×MSK weight
- Fine-tune fairness for specialty combinations

---

## Skill Dashboard

Guardrails for the skill selector UI.

```yaml
skill_dashboard:
  hide_invalid_combinations: false  # Hide skill buttons that don't apply to the modality
```

Set to `true` to hide non-applicable skills on each modality tab. Uses `valid_skills`/`hidden_skills` on modalities and `valid_modalities`/`hidden_modalities` on skills.

---

## Skill Value Colors

How skill values appear in the prep page table.

```yaml
skill_value_colors:
  active:     # skill = 1 (primary assignment)
    color: '#28a745'
    label: 'Active'
  passive:    # skill = 0 (fallback only)
    color: '#6c757d'
    label: 'Passive'
  excluded:   # skill = -1 (never assign)
    color: '#dc3545'
    label: 'Excluded'
  weighted:   # skill = 'w' (assisted/weighted)
    color: '#17a2b8'
    label: 'Weighted'
```

---

## UI Colors

Top-level UI theme settings.

```yaml
ui_colors:
  today_tab: '#28a745'        # Green for "Change Today"
  tomorrow_tab: '#ffc107'     # Yellow for "Prep Tomorrow"
  success: '#28a745'
  error: '#dc3545'
  warning: '#ffc107'
  info: '#17a2b8'
```

---

## Balancer Settings

Control load balancing behavior and hours counting.

```yaml
balancer:
  enabled: true
  min_assignments_per_skill: 5    # Minimum weighted assignments
  imbalance_threshold_pct: 30     # Trigger fallback at 30% imbalance
  allow_fallback_on_imbalance: true
  modifier_applies_to_active_only: true  # Modifier only for skill=1

  # Hours counting for workload calculation
  hours_counting:
    shift_default: true   # type: "shift" entries count towards hours (default)
    gap_default: false    # type: "gap" entries don't count towards hours (default)

  # Exclusion-based routing configuration
  exclusion_rules:
    # Define which workers to EXCLUDE when requesting each skill
    # Workers with excluded_skill=1 won't receive work for this skill
    Notfall:
      exclude_skills: []  # No exclusions
    Privat:
      exclude_skills: []
    Gyn:
      exclude_skills: []
    Päd:
      exclude_skills: []
    MSK:
      exclude_skills: []
    Abdomen:
      exclude_skills: []
    Chest:
      exclude_skills: []
    Cardvask:
      exclude_skills: []
    Uro:
      exclude_skills: []
```

### Exclusion-Based Routing

The system uses exclusion-based selection to distribute work fairly while respecting specialty boundaries:

**Two-Level Fallback:**

1. **Level 1 (Exclusion-based):**
   - Filter to workers with requested skill≥0 (excludes -1)
   - Remove workers with excluded skills=1
   - Calculate workload ratio for each candidate (weighted_count / hours_worked)
   - Select worker with lowest ratio

2. **Level 2 (Skill-based fallback):**
   - If Level 1 produces no candidates, ignore exclusions
   - Filter to workers with requested skill≥0 (active or passive)
   - Select worker with lowest ratio

Use exclusions to block specific specialists from receiving unrelated work (e.g., keep MSK team off Cardvask requests).

**Example:** Keep Cardvask requests away from MSK specialists unless no one else is available.
```yaml
exclusion_rules:
  Cardvask:
    exclude_skills: [MSK]
```

### Two-Phase Minimum Balancer

**Phase 1 (No-Overflow):** Until all ACTIVE workers (skill ≥ 1) reach minimum weighted assignments, restrict pool to underutilized workers.

**Phase 2 (Normal Mode):** Once all active workers have minimum, allow normal weighted overflow.

---

## Modality Fallbacks

Configure cross-modality overflow when a modality has no available workers.

```yaml
modality_fallbacks:
  xray: [[ct, mr]]   # XRAY can borrow from CT AND MR (parallel)
  ct: [mr]           # CT can borrow from MR only
  mr: []             # MR cannot borrow
  mammo: []          # Mammo cannot borrow
```

---

## Medweb CSV Mapping

Map activity descriptions from medweb CSV to modalities and skills. Rules support **shifts** (work assignments) and **gaps** (unavailability such as boards/meetings). Pre/post buffers are no longer supported—gaps use only the scheduled window.

```yaml
medweb_mapping:
  # Rules are evaluated in order; first match wins
  rules:
    # ============================
    # SHIFTS / ROLES
    # ============================
    - match: "CT Spätdienst"
      type: "shift"
      modality: "ct"
      shift: "Spaetdienst"
      base_skills: {Notfall: 1, Privat: 0, Gyn: 0, Päd: 0, MSK: 0, Abdomen: 0, Chest: 0, Cardvask: 0, Uro: 0}

    - match: "MR Assistent 1. Monat"
      type: "shift"
      modality: "mr"
      shift: "Fruehdienst"
      base_skills: {Notfall: 0, Privat: 0, Gyn: 0, Päd: 0, MSK: 0, Abdomen: 0, Chest: 0, Cardvask: 0, Uro: 0}

    # Multi-modality assignment
    - match: "MSK Assistent"
      type: "shift"
      modalities: ["xray", "ct", "mr"]
      shift: "Fruehdienst"
      base_skills: {Notfall: 0, Privat: 0, Gyn: 0, Päd: 0, MSK: 1, Abdomen: 0, Chest: 0, Cardvask: 0, Uro: 0}

    # Weighted entry (assisted worker)
    - match: "MSK Anfänger"
      type: "shift"
      modalities: ["xray", "ct"]
      shift: "Fruehdienst"
      base_skills: {Notfall: 0, Privat: 0, Gyn: 0, Päd: 0, MSK: w, Abdomen: 0, Chest: 0, Cardvask: 0, Uro: 0}
      modifier: 0.5  # Lower capacity → counts double toward load

    # Hours that should NOT count toward load balancing
    - match: "Cortex Aufklärung"
      type: "shift"
      modality: "ct"
      shift: "Fruehdienst"
      label: "Aufklärung"
      counts_for_hours: false
      base_skills: {Notfall: 0, Privat: 0, Gyn: 0, Päd: 0, MSK: 0, Abdomen: 0, Chest: 0, Cardvask: 0, Uro: 0}

    # ============================
    # GAPS / TASKS (unavailability)
    # ============================
    - match: "Kopf-Hals-Board"
      type: "gap"
      exclusion: true
      schedule:
        Montag: "15:30-17:00"

    - match: "Board"
      type: "gap"
      exclusion: true
      schedule:
        Dienstag: "15:00-17:00"
        Mittwoch: "10:00-12:00"
        Donnerstag: "14:00-16:00"
```

**Rule matching:** First match wins. Order rules from specific to general.

**Multi-modality:** Use `modalities: [...]` instead of a single `modality` key.

**Weighted / assisted shifts:** Use `base_skills: {Skill: w}` plus a `modifier` (0.5–1.5) to set workload impact.

**Hours counting:**
- Shifts count toward workload unless `counts_for_hours: false`.
- Gaps do **not** count toward workload unless `counts_for_hours: true` (defaults come from `balancer.hours_counting`).

**Time exclusions:** Gaps simply block the scheduled window—there are no pre/post buffers.

---

## Shift Times

Define shift time windows with optional Friday exceptions.

```yaml
shift_times:
  Fruehdienst:
    default: "07:00-15:00"
    friday: "07:00-13:00"    # Shorter Friday shift
  Spaetdienst:
    default: "13:00-21:00"
    friday: "13:00-19:00"
```

Overnight shifts (e.g., `22:00-06:00`) are automatically handled by rolling end time to next day.

---

## Worker Skill Matrix

Per-worker skill overrides. Takes precedence over `medweb_mapping.base_skills`.

```yaml
worker_skill_roster:
  # MSK specialist
  AA:
    default:
      Notfall: 1
      Privat: 0
      Gyn: 0
      Päd: 0
      MSK: 1      # MSK specialist
      Abdomen: 0
      Chest: 0
      Cardvask: 0
      Uro: 0

  # Chest specialist with CT-specific override
  AN:
    default:
      Notfall: 1
      Privat: 0
      Gyn: 0
      Päd: 0
      MSK: 0
      Abdomen: 0
      Chest: 1    # Chest specialist
      Cardvask: 0
      Uro: 0
    ct:
      Notfall: 0  # Only fallback for CT Notfall

  # Cardiac specialist, excluded from MSK/Chest
  DEMO1:
    default:
      Notfall: 1
      Privat: 0
      Gyn: 0
      Päd: 0
      MSK: -1       # NEVER for MSK
      Abdomen: 0
      Chest: -1     # NEVER for Chest
      Cardvask: 1   # Cardiac specialist
      Uro: 0
```

**Precedence:** `worker_skill_roster` > `medweb_mapping.base_skills` > defaults.

**Modality-specific:** Add modality key (e.g., `ct:`) under a worker to override for that modality only.

**Value legend:** `1` = primary, `0` = fallback, `-1` = never, `w` = weighted/assisted.

---

## Complete Example

```yaml
admin_password: change_for_production

modalities:
  ct:
    label: CT
    factor: 1.0
  mr:
    label: MR
    factor: 1.2
  xray:
    label: XRAY
    factor: 0.33
  mammo:
    label: Mammo
    factor: 0.5
    valid_skills: [Notfall, Privat, Gyn]

skills:
  Notfall:
    weight: 1.1
    optional: false
  Privat:
    weight: 1.2
    optional: true
  Cardvask:
    weight: 1.2
    optional: true
    special: true

skill_modality_overrides:
  mr:
    Cardvask: 1.8  # MR cardiac work weighted higher

skill_dashboard:
  hide_invalid_combinations: false

balancer:
  enabled: true
  min_assignments_per_skill: 5
  imbalance_threshold_pct: 30
  allow_fallback_on_imbalance: true
  modifier_applies_to_active_only: true
  hours_counting:
    shift_default: true
    gap_default: false
  exclusion_rules:
    Cardvask:
      exclude_skills: [MSK]
    Notfall:
      exclude_skills: []

modality_fallbacks:
  xray: [[ct, mr]]
  ct: [mr]
  mr: []
  mammo: []

medweb_mapping:
  rules:
    - match: "CT Assistent"
      type: "shift"
      modality: "ct"
      shift: "Fruehdienst"
      base_skills: {Notfall: 1, Privat: 0, Cardvask: 0}
    - match: "Kopf-Hals-Board"
      type: "gap"
      exclusion: true
      schedule:
        Montag: "15:30-17:00"

shift_times:
  Fruehdienst:
    default: "07:00-15:00"
    friday: "07:00-13:00"

worker_skill_roster:
  DEMO:
    default:
      Notfall: 1
      Cardvask: 1
      MSK: -1
```

---

## Tips

1. **Adding new activity**: Add rule to `medweb_mapping.rules`, restart app
2. **Adjusting worker skills**: Update `worker_skill_roster`, restart app
3. **Fine-tuning balance**: Adjust `skill_modality_overrides` for specific combinations
4. **Testing config**: Run `python ops_check.py` to validate
