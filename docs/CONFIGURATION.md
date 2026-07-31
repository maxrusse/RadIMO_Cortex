# RadIMO Configuration Reference

Create a local runtime file with `cp config.demo.yaml config.yaml`. Keep that
local file out of version control. The demo values for passwords are deliberate
placeholders: replace them in a live deployment and do not copy live credentials
into documentation, tickets, or exports.

## Reloading and the settings UI

Most scalar configuration changes can be reloaded at runtime. The admin
**Settings** page (`/admin/settings`) edits only these fields:

- `default_language` (`de` or `en`)
- `timezone`
- `worker_name_display_style` (`first_last_id`, `last_first_id`, or `raw`)
- `skill_roster_auto_import`
- `access_protection_enabled`
- `admin_access_protection_enabled`

It does not display or edit `secret_key`, `access_password`, or
`admin_password`. Advanced YAML replacement validates the candidate, makes a
backup, and reloads what can be applied safely. Structural changes to
`modalities`, `skills`, or `secret_key` require an application restart.

## Top-level settings

| Key | Meaning |
|---|---|
| `secret_key` | Flask session signing key; set a unique secret in production. |
| `access_protection_enabled`, `access_password` | Optional protection for normal operational pages. |
| `admin_access_protection_enabled`, `admin_password` | Optional protection for admin pages. |
| `default_language` | Default UI language (`de` or `en`). |
| `timezone` | IANA timezone used by application date/time helpers. |
| `skill_roster_auto_import` | Adds workers missing from the skill roster during CSV processing. |
| `worker_name_display_style` | Display style; top-level value takes precedence over the Medweb value. |

## Modalities and skills

`modalities` and `skills` define the current valid configuration; the runtime
does not add hard-coded fallback CT/MR/X-ray entries. Use safe identifiers with
neither spaces nor underscores because skill-modality keys use `_` as a
separator.

```yaml
modalities:
  ct:
    label: CT
    nav_color: '#005ea8'
    hover_color: '#00467d'
    background_color: '#d7eaf7'
    hidden_skills: [gyn]       # optional

skills:
  cvt:
    label: CVT
    slug: cvt
    display_order: 1
    button_color: '#bd5717'
    text_color: '#ffffff'
    special: true
    tooltip: Cardio / Vask / Thorax       # optional
    show_abbreviation_hint: true          # optional
    valid_modalities: [ct, mr]            # optional
    hidden_modalities: [xray]             # optional
```

For modalities, `label`, `nav_color`, `hover_color`, and `background_color`
have runtime defaults when omitted. Skills similarly default `label`, colors,
`special`, `display_order`, and a slug generated from the key. `valid_skills`
and `hidden_skills` are modality visibility filters; `valid_modalities` and
`hidden_modalities` are skill visibility filters.

## Routing and button weights

Button weights are managed separately in `data/button_weights.json` through
`/button-weights`; they are not `config.yaml` keys. Normal weights apply to the
normal route. Strict weights apply only to the explicit `/api/{modality}/{role}/strict` routes.

`no_overflow` is a list of `skill_modality` keys. It makes the normal assignment
route specialist-only (`1` or `w`) but does not switch it to strict weights.
`strict_button_visibility` controls whether a Live view displays a strict `*`
button. Each key may be `true` or an object with `visible` and `manual_select`.
The latter enables the strict candidates/manual routes for that button.

`specialist_fallback_routes` maps a primary skill to fallback skills. The
runtime tries the primary specialist pool first, then the configured merged
specialist pools in the same modality. If overflow is permitted, generalist
fallback remains available only after those specialist pools are empty.

```yaml
no_overflow: [gyn_ct]
strict_button_visibility:
  cvt_ct: {visible: true, manual_select: true}
specialist_fallback_routes:
  aou: [mdh]
```

## Special tasks and synthetic shifts

`special_tasks` add distinct Live-view buttons while routing through a
`base_skill`. Supported fields are `name`, `label`, `base_skill`, optional
`target_skill_modalities`, `modalities_dashboards`, `skill_dashboards`,
`allow_overflow`, `display_order`, and `tooltip`. An explicit target list is a
list of `skill_modality` keys and is used as the routing pool. A task with
`allow_overflow: false` remains on normal weights unless called through
`/api/{modality}/{role}/strict`.

```yaml
special_tasks:
  - name: aou_ct-seg
    label: Organ Seg
    base_skill: aou
    target_skill_modalities: [aou_ct, aou_mr]
    skill_dashboards: [aou]
    allow_overflow: false
```

`synthetic_shifts` inject configured workers even without a Medweb row. The
demo configuration uses `worker_name`, `use_shift`, and `weekdays`; `use_shift`
selects matching configured shift behavior. `worker_roster` supplies persistent
per-worker baseline values. In skill mappings, `-1` excludes, `0` is passive
generalist fallback, `1` is active specialist, and `w` is weighted/assisted.

## Balancer, scheduler, and UI

`balancer` accepts `enabled`, `min_assignments_per_skill`,
`warm_start_release_mode`, `imbalance_threshold_pct`,
`disable_overflow_at_shift_start_minutes`,
`disable_overflow_at_shift_end_minutes`, and `default_w_modifier`. The demo
also configures `hours_counting`, `quick_break`, and `exclude_skills` beneath
it. `worker_load_monitor` configures absolute/relative color thresholds and
the default view. `skill_value_colors` and `ui_colors` are presentation-only.

`scheduler.daily_reset_time` and `scheduler.auto_preload_time` configure the
day-plan scheduler. They do not control usage-statistics rollover, which is
date-change driven by the usage logger.

## Medweb mapping

`vendor_mappings.medweb` contains `worker_name_display_style`, source-column
names, and ordered mapping `rules`. Rule order matters: the first matching rule
wins. The tracked demo file is the authoritative template for its supported
shift/gap rule shapes, including `match`, `type`, `day_part`/`day_parts`,
`times`, `skill_overrides`, `modifier`, and `counts_for_hours`.

Use full `skill_modality` values in `skill_overrides`; starting a rule with
`all: -1` and explicitly reopening permitted combinations makes the resulting
pool clear. Do not invent modality-only or skill-only shorthand keys.
