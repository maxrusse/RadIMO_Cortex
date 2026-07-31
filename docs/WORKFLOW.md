# RadIMO Cortex workflow

## Daily operation

1. Upload the current Medweb export in **Tools → Import** (`/upload`). It is stored as `uploads/master_medweb.csv`.
2. Use **Today** (`/prep-today`) only for changes to the current live schedule. These changes apply immediately and do not reset counters.
3. Use **Planning** (`/prep-tomorrow`) to prepare a selected future workday. Reloading that target date from the Master CSV replaces that staged day.
4. Use **HARD RELOAD TODAY** on Import only when the live day genuinely must be rebuilt from the Master CSV. It resets the live assignment counters.

Uploading a Master CSV does not overwrite an existing Planning snapshot. Reload Planning explicitly for the desired date.

## Schedule and assignment model

- `config.yaml` is the active local configuration. Start a new instance by copying the tracked `config.demo.yaml`; never put live credentials in the demo file.
- Mapping rules turn CSV activities into modality, shift, and optional skill overrides. Keep rules ordered from specific to general: first match wins.
- Shifts are same-day windows: the end time must be later than the start time.
- Meetings, boards, and breaks create gap segments. Only shift segments provide availability.
- The Skill Matrix (`/skill-roster`) holds persistent worker baselines. `1` and `w` are active, `0` is fallback/generalist, and `-1` is excluded. Shift and live/planning edits determine the active day state.
- Assignment uses active shift availability, configured eligibility, button weights, modifiers, and overflow rules.

## Automation and verification

- The configured daily reset time is `scheduler.daily_reset_time` (the demo value is `07:30`). It promotes the dated staged snapshot to the live day and resets daily counters when the application next performs its reset check.
- Planning is also loaded on demand when required; do not assume an unattended preload succeeded. Check Planning and `/readyz` before the next workday.
- Use **Tools → Status** (`/status`) or `/readyz` after configuration, import, or recovery work. Review `logs/selection.log` for reset and loading messages.

## Admin navigation

The primary admin navigation is **Analysis**, **Workload**, **Today**, **Planning**, **Schedule**, and **Live**. The **Tools** menu contains **Overview**, **Settings**, **Corrections**, **Skills**, **Weights**, **Import**, **Files**, **Logs**, and **Status**.
