# RadIMO Cortex admin guide

Admin access is controlled by `admin_access_protection_enabled` and `admin_password` in the local `config.yaml`. If basic access protection is enabled separately, operational users sign in at `/access-login`; administrators use `/login`.

## Navigation

The top admin navigation provides **Analysis**, **Workload**, **Today**, **Planning**, **Schedule**, and **Live**. The **Tools** menu provides:

| Tool | Route | Use |
|---|---|---|
| Overview | `/admin/tools` | readiness, managed-file summary, and guarded app reload |
| Settings | `/admin/settings` | general configuration settings |
| Corrections | `/manual-adjustments` | manual load corrections |
| Skills | `/skill-roster` | persistent worker skill baselines |
| Weights | `/button-weights` | normal/strict button and special-task weights |
| Import | `/upload` | Master CSV upload and live-day rebuild |
| Files | `/admin/files` | managed config, roster, live backup, and staged-day files |
| Logs | `/admin/logs` | browser access to supported logs |
| Status | `/status` | health and readiness checks |

## Schedule work

### Today (`/prep-today`)

Use **Today** for sickness, time corrections, coverage changes, and gaps affecting the live day. Saving a change updates the live schedule without resetting assignment counters. Use the gap controls to split availability around meetings, boards, or breaks.

### Planning (`/prep-tomorrow`)

Use **Planning** for a selected future workday. It is a staged schedule and does not alter today's live assignments. Reloading the selected date from the Master CSV replaces that date's staged data, so check the target date before confirming.

### Import and HARD RELOAD TODAY (`/upload`)

Upload the current Medweb CSV first. The file becomes `uploads/master_medweb.csv`; upload alone does not change Today or overwrite Planning. **HARD RELOAD TODAY** rebuilds the live day from that CSV and resets live counters. It is a recovery/rebuild action, not the normal way to make a same-day edit.

## Skills and weights

The Skill Matrix stores baseline eligibility in `data/worker_skill_roster.json`:

- `1`: active specialist
- `w`: active weighted/training role
- `0`: passive/generalist fallback
- `-1`: excluded

The Weight Matrix stores normal and strict assignment weights in `data/button_weights.json`. A blank weight uses the configured default. Changes to either page are persistent; check the relevant Live view after saving.

## Configuration, files, and recovery

- `config.demo.yaml` is a tracked example. Create and maintain the active `config.yaml` locally; keep production credentials out of source control.
- In **Files**, upload/restore only the explicitly named managed file and use its reload action where offered. Structural config changes (modalities, skills, or session secret) require a process restart; ordinary settings can be reloaded when the page reports that reload is supported.
- **Overview → Reload app** sends a guarded Gunicorn worker reload and is available only when the app is actually running under Gunicorn. It is not a substitute for deploying code or resolving failed readiness checks.
- Before manual filesystem recovery, take a dated backup of `data/` and `uploads/`. Do not delete CSVs, roster data, weights, or backup directories as a routine reset. Prefer the Files UI and preserve evidence for escalation.

## Operational checks

Use `/healthz` for a basic health response and `/readyz` (or **Status**) for readiness details. Logs provides current and rotated `gunicorn.log`, `selection.log`, `flow_balance.log`, and `import.log`; `selection.log` is the primary application log and `import.log` records CSV/preload and generated-schedule JSON events, including parse failures.

At the configured daily reset time (`scheduler.daily_reset_time`, demo: `07:30`), the app promotes the staged day and resets daily counters. Review Today and readiness on the next workday; Planning may also be loaded lazily when requested.
