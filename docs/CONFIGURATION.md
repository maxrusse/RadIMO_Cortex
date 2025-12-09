# RadIMO Configuration Reference

Complete reference for `config.yaml` settings.

---

## Overview

RadIMO uses a single `config.yaml` file for all configuration. Changes require application restart unless otherwise noted.

```yaml
# Main sections
admin_password: "..."      # Admin login
modalities: {...}          # CT, MR, XRAY definitions
skills: {...}              # Skill definitions and weights
skill_modality_overrides: {...}  # Custom weight overrides
balancer: {...}            # Load balancing settings
modality_fallbacks: {...}  # Cross-modality overflow
medweb_mapping: {...}      # CSV activity parsing
shift_times: {...}         # Shift time definitions
worker_skill_roster: {...} # Per-worker skill overrides
```

---

## Modalities

Define available modalities with display and weighting settings.

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
```

**Factor**: Higher factor = work counts more toward weighted total. Use to balance effort across modalities.

---

## Skills

Define skills with weights and UI settings.

```yaml
skills:
  Normal:
    label: Normal          # Display name
    button_color: '#004892'
    text_color: '#ffffff'
    weight: 1.0            # Base weight
    optional: false        # Always shown
    special: false         # Not a specialty skill
    always_visible: true
    display_order: 0       # Button order
    fallback: []           # No fallback
    slug: normal           # URL-safe name
    form_key: normal       # Form field name

  Notfall:
    label: Notfall
    button_color: '#dc3545'
    text_color: '#ffffff'
    weight: 1.1            # 10% more than Normal
    optional: false
    special: false
    always_visible: true
    display_order: 1
    fallback:
      - Normal             # Falls back to Normal
    slug: notfall
    form_key: notfall

  Herz:
    label: Herz
    button_color: '#28a745'
    text_color: '#ffffff'
    weight: 1.2            # 20% more than Normal
    optional: true         # Only shown when workers available
    special: true          # Specialty skill
    always_visible: false
    display_order: 3
    fallback:
      - [Notfall, Normal]  # Parallel fallback
    slug: herz
    form_key: herz
```

**Fallback syntax:**
- `[Normal]` - Sequential: try Normal
- `[[Notfall, Normal]]` - Parallel: try Notfall AND Normal simultaneously

---

## Skill×Modality Weight Overrides

Override the default `skill_weight × modality_factor` calculation for specific combinations.

```yaml
skill_modality_overrides:
  mr:
    Herz: 1.8        # MR×Herz = 1.8 (instead of 1.2×1.2=1.44)
    Notfall: 1.5     # MR×Notfall = 1.5 (instead of 1.1×1.2=1.32)
  ct:
    Chest: 1.0       # CT×Chest = 1.0 (instead of 1.0×0.8=0.8)
```

**How it works:**
1. Check `skill_modality_overrides[modality][skill]` for explicit value
2. If not found, calculate: `skill_weight × modality_factor`

**Use cases:**
- Cardiac MR is more demanding → increase MR×Herz weight
- XRAY MSK is simpler → decrease XRAY×Msk weight
- Fine-tune fairness for specialty combinations

---

## Balancer Settings

Control load balancing behavior.

```yaml
balancer:
  enabled: true
  min_assignments_per_skill: 5    # Minimum weighted assignments
  imbalance_threshold_pct: 30     # Trigger fallback at 30% imbalance
  allow_fallback_on_imbalance: true
  modifier_applies_to_active_only: true  # Modifier only for skill=1

  # Exclusion-based routing (NEW)
  use_exclusion_routing: true
  exclusion_rules:
    # Define which workers to EXCLUDE when requesting each skill
    # Workers with excluded_skill=1 won't receive work for this skill
    Privat:
      exclude_skills: []         # No exclusions
    Notfall:
      exclude_skills: []
    Herz:
      exclude_skills: [Chest, Msk]  # Chest/Msk specialists don't get Herz
    Normal:
      exclude_skills: []
    Msk:
      exclude_skills: []
    Chest:
      exclude_skills: []

  # Legacy fallback_chain (only used when use_exclusion_routing=false)
  fallback_chain:
    Normal: []
    Notfall: [Normal]
    Privat: [Notfall, Normal]
    Herz: [[Notfall, Normal]]     # Parallel fallback
    Msk: [[Notfall, Normal]]
    Chest: [[Notfall, Normal]]
```

### Exclusion-Based Routing

The system uses exclusion-based selection to distribute work fairly while respecting specialty boundaries:

**Three-Level Fallback:**

1. **Level 1 (Exclusion-based):**
   - Start with ALL available workers across all skills
   - Remove workers with excluded skills (value=1)
   - Calculate workload ratio for each candidate (weighted_count / hours_worked)
   - Select worker with lowest ratio

2. **Level 2 (Skill-based fallback):**
   - If Level 1 produces no candidates, ignore exclusions
   - Try workers with requested skill≥0 (active or passive)
   - Select worker with lowest ratio

3. **Level 3:** No assignment possible

**Example:**
```yaml
exclusion_rules:
  Herz:
    exclude_skills: [Chest, Msk]
```

- **Request:** Herz work needed
- **Level 1:** Try ALL workers EXCEPT Chest=1 and Msk=1 workers → Pick lowest ratio
- **Level 2 (if empty):** Try workers with Herz≥0 → Pick lowest ratio
- **Level 3:** No assignment

**Toggle Between Strategies:**
- Set `use_exclusion_routing: true` for exclusion-based routing (NEW)
- Set `use_exclusion_routing: false` for legacy pool-based routing with fallback chains

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
```

---

## Medweb CSV Mapping

Map activity descriptions from medweb CSV to modalities and skills.

```yaml
medweb_mapping:
  rules:
    # Single modality assignment
    - match: "CT Spätdienst"
      modality: "ct"
      shift: "Spaetdienst"
      base_skills: {Normal: 1, Notfall: 1, Privat: 0, Herz: 0, Msk: 0, Chest: 0}

    # First month assistant (restricted skills)
    - match: "MR Assistent 1. Monat"
      modality: "mr"
      shift: "Fruehdienst"
      base_skills: {Normal: 1, Notfall: 0, Privat: 0, Herz: 0, Msk: 0, Chest: 0}

    # Multi-modality assignment (sub-specialty teams)
    - match: "MSK Assistent"
      modalities: ["xray", "ct", "mr"]  # Available in all three
      shift: "Fruehdienst"
      base_skills: {Normal: 0, Notfall: 0, Privat: 0, Herz: 0, Msk: 1, Chest: 0}

    # Time exclusion (boards, meetings)
    - match: "Kopf-Hals-Board"
      exclusion: true
      schedule:
        Montag: "15:30-17:00"
        Dienstag: "15:00-17:00"
      prep_time:
        before: "30m"    # Prep time before meeting
        after: "15m"     # Cleanup time after
```

**Rule matching:** First match wins. Order rules from specific to general.

**Multi-modality:** Use `modalities: [...]` list instead of single `modality: "..."`.

**Time exclusions:** Automatically split shifts around scheduled meetings.

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

Per-worker skill overrides. Takes precedence over medweb_mapping base_skills.

```yaml
worker_skill_roster:
  # MSK specialist
  AA:
    default:
      Normal: 1
      Notfall: 1
      Privat: 0
      Herz: 0
      Msk: 1        # MSK specialist
      Chest: 0

  # Chest specialist with CT-specific override
  AN:
    default:
      Normal: 1
      Notfall: 1
      Privat: 0
      Herz: 0
      Msk: 0
      Chest: 1      # Chest specialist
    ct:
      Notfall: 0    # Only fallback for CT Notfall

  # Excluded from certain skills
  DEMO1:
    default:
      Normal: 1
      Notfall: 1
      Privat: 0
      Herz: 1       # Cardiac specialist
      Msk: -1       # NEVER for MSK
      Chest: -1     # NEVER for Chest
```

**Precedence:** `worker_skill_roster` > `medweb_mapping.base_skills` > defaults

**Modality-specific:** Add modality key (e.g., `ct:`) under worker to override for that modality only.

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

skills:
  Normal:
    weight: 1.0
    optional: false
  Notfall:
    weight: 1.1
    fallback: [Normal]
  Herz:
    weight: 1.2
    optional: true
    special: true
    fallback: [[Notfall, Normal]]

skill_modality_overrides:
  mr:
    Herz: 1.8      # MR cardiac work weighted higher

balancer:
  enabled: true
  min_assignments_per_skill: 5
  imbalance_threshold_pct: 30

modality_fallbacks:
  xray: [[ct, mr]]
  ct: [mr]
  mr: []

medweb_mapping:
  rules:
    - match: "CT Assistent"
      modality: "ct"
      shift: "Fruehdienst"
      base_skills: {Normal: 1, Notfall: 1}

shift_times:
  Fruehdienst:
    default: "07:00-15:00"
    friday: "07:00-13:00"

worker_skill_roster:
  DEMO:
    default:
      Herz: 1
```

---

## Tips

1. **Adding new activity**: Add rule to `medweb_mapping.rules`, restart app
2. **Adjusting worker skills**: Update `worker_skill_roster`, restart app
3. **Fine-tuning balance**: Adjust `skill_modality_overrides` for specific combinations
4. **Testing config**: Run `python ops_check.py` to validate
