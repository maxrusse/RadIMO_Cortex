# RadIMO SBZ Coordinator

RadIMO orchestrates modality-specific reading workloads for radiology teams. The
Flask application ingests structured Excel schedules, tracks how often each
radiologist has been assigned to Normal, Notfall, Privat, Herz, Msk, and Chest
cases, and automatically balances future assignments across modalities. The tool
is designed for medical workload distribution scenarios where CT, MR, and X-Ray
teams share staff and overflow logic must be transparent.

## Key Features

- **Excel-based roster ingestion** – upload or schedule modality-specific XLSX
  files that define people, time windows, modifiers, and per-skill capacities.
- **Real-time coordinator UI** – modality tabs, skill buttons, and live status
  indicators show who can be assigned at any moment (`templates/index.html`).
- **Weighted workload tracking** – modifiers, modality factors, and skill
  weights are combined inside `update_global_assignment` to keep global totals
  fair across teams (`app.py`).
- **Strict group draws** – each skill button exposes a star `*` control that
  forces the request through `/api/<modality>/<role>/strict`, ensuring no
  fallback columns or modalities are used when you need a dedicated worker.
- **Automatic backups & reset flow** – every upload produces a live backup and a
  07:30 CET daily reset consumes scheduled files, guaranteeing recoverability.
- **REST API** – `/api/<modality>/<role>` drives remote dashboards or bots,
  `/api/<modality>/<role>/strict` enforces "no fallback" pulls for that role,
  and `/api/quick_reload` exposes assignment statistics for tooling
  integrations.

## Running the Application

1. **Install dependencies** (Flask, pandas, openpyxl, PyYAML).

   ```bash
   pip install -r requirements.txt  # or install the packages manually
   ```

2. **Inspect operational readiness** (optional):

   ```bash
   python ops_check.py
   ```

   The script loads `app.py`, prints configured modalities/skills, and runs the
   inline operational checks.

3. **Start the coordinator**:

   ```bash
   flask --app app run --debug
   ```

   Upload live rosters via `/upload` (admin login) or monitor assignments via
   `/`.

## Upload & Scheduling Workflow

- Each modality has a default upload (`uploads/SBZ_<MOD>.xlsx`) plus an optional
  scheduled file (`uploads/SBZ_<MOD>_scheduled.xlsx`).
- Uploads immediately reset draw counters, skill counters, and weighted counts
  before re-importing (`upload_file` view).
- Daily at 07:30 CET, `check_and_perform_daily_reset` consumes scheduled files,
  backs them up, and refreshes live data without manual interaction.

## Overflow & Modular Fallback Logic

1. **Skill-level overflow detection**

   - `_apply_minimum_balancer` favors workers who have been assigned fewer times
     than `balancer.min_assignments_per_skill` for the active skill column.
   - `_should_balance_via_fallback` compares the max/min draw counts for all
     workers who can currently serve a skill. If the imbalance exceeds
     `balancer.imbalance_threshold_pct`, the system temporarily routes the
     request to a fallback skill column.

2. **Skill fallback chains**

   - `_try_configured_fallback` iterates through the ordered list defined in
     `balancer.fallback_chain` (defaults live in `config.yaml`).
   - `get_active_df_for_role` will transparently switch to the first fallback
     column that still has capacity, so "Herz" can borrow "Notfall" workers and
     ultimately "Normal" staff when demand spikes.

3. **Modality-level overflow chains**

   - The new `modality_fallbacks` map (see `config.yaml`) describes which other
     modalities can cover a shortage (e.g., XRAY → CT → MR).
   - `get_next_available_worker` now walks `[requested_modality] + fallback
     chain`, calling `_select_worker_for_modality` at each step until a worker
     is found. The response clearly states the modality actually used so the UI
     can highlight cross-team support.

Together, these layers give planners a modular control surface: per-skill
fallbacks handle intra-modality overloads, while modality fallback chains enable
cross-modality surge absorption. Both behaviors are data-driven via YAML.

## Configuration Reference (`config.yaml`)

- **modalities** – label, colors, and weighting factor per modality.
- **skills** – label, colors, weight, optional/special flags, form_key/slug, and
  `display_order` for UI ordering. Skills inherit sensible defaults from
  `DEFAULT_SKILLS` if a field is omitted.
- **balancer** – enable/disable minimum assignment logic, imbalance thresholds,
  and skill fallback chains.
- **modality_fallbacks** – ordered arrays such as `xray: [ct, mr]` that define
  the modular overflow path for `get_next_available_worker`.
- **admin_password** – protects `/upload` via the simple login form.

Any change to `config.yaml` is merged with defaults when the app starts, so you
only have to maintain a single configuration file.

## API Surface

| Endpoint | Purpose |
| --- | --- |
| `/api/<modality>/<role>` | Draws and logs the next worker for the given modality & skill. |
| `/api/<modality>/<role>/strict` | Same as above but refuses skill/modality fallbacks for the request. |
| `/api/quick_reload` | Returns live stats, available buttons, and operational check results. |
| `/timetable` | Visualizes current working-hours windows per modality. |

Responses contain the assigned person, updated totals, and any fallback
information so downstream systems can mirror the UI.

## Usage Ideas for Medical Workload Distribution

- **Central dispatcher consoles** – run the UI on a modality workstations so coordinators
  can trigger assignments in real time.
- **Operations analytics** – poll `/api/quick_reload` to feed dashboards that
  highlight when certain skills or modalities routinely overflow.
- **Cross-site coordination** – configure modality fallbacks to point to other
  campuses, enabling remote coverage when local staff is exhausted.

These scenarios all benefit from RadIMO's transparent overflow logic and the
ability to encode modality/skill relationships declaratively.
