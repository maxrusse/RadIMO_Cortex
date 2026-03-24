# RadIMO Cortex

**Intelligent Radiology Orchestration**

Worker assignment for radiology teams with automatic load balancing, skill-aware routing, and shift-based fairness.

---

## What is RadIMO Cortex?

RadIMO Cortex orchestrates workload distribution for radiology teams across CT, MR, and XRAY using skills such as Notfall, Privat, Gyn, AOU, CVT, and MHD. It balances assignments for fairness while respecting availability, shift timing, and skill levels.

**Key capabilities:**
- Real-time worker assignment with automatic load balancing
- Skill-based routing with configurable exclusion rules
- Dynamic shift handling with work-hour-adjusted balancing
- Two UI modes: by modality or by skill
- Two-level fallback for high availability
- Master CSV integration for monthly schedule management
- Admin system: Skill Matrix (direct save), Schedule Edit (Today + Prep Tomorrow)
- Worker skill roster admin portal with simplified JSON management
- GAP handling (split shifts) for meetings and boards
- Smart skill filtering on Schedule Edit and Timetable views
- Special tasks for custom sub-workflows with separate tracking
- Recurring synthetic shift workers defined in config for summary roles
- Shared timeline rendering for timetable + prep/change pages

---

## Quick Start

### Installation

```bash
pip install -r requirements.txt
python scripts/ops_check.py  # Check system readiness
python scripts/gen_test_data.py --scenario all  # Generate deterministic test fixtures (optional)
python scripts/apply_demo_data.py  # Prepare deterministic UI demo data
python scripts/capture_screenshots.py  # Generate training screenshots + manifest
flask --app app run --debug  # Start application
```

### Access Points

**Operational pages (access-protected if enabled):**
| Page | URL | Description |
|------|-----|-------------|
| Main Interface | `/` | Assignment by modality (CT/MR/XRAY) |
| Skill View | `/by-skill` | Assignment by skill (Notfall, CVT, MHD, etc.) |
| Timetable | `/timetable` | Visualize shifts and schedules |

If basic access protection is enabled, users authenticate via `/access-login` before reaching the operational pages.
Admin pages require a session via `/login` when `admin_access_protection_enabled` is true.

**Admin pages (password protected when enabled):**
| Page | URL | Description |
|------|-----|-------------|
| Admin Panel | `/upload` | Master CSV upload and `HARD RELOAD TODAY` |
| Skill Matrix | `/skill-roster` | Edit worker skills (Direct Save) |
| Schedule Edit (Today) | `/prep-today` | Edit today (live) |
| Schedule Edit (Tomorrow) | `/prep-tomorrow` | Prep tomorrow (staged) |
| Worker Load | `/worker-load` | Load monitoring dashboard |
| Weight Matrix | `/button-weights` | Configure button weights and special tasks |

---

## Core Workflow

Master CSV (current source file)
    ↓
Upload via /upload (Master CSV)
    ↓
HARD RELOAD TODAY (Live) or Prep Tomorrow reload (Staged)
    ↓
Config-driven parsing (medweb_mapping rules)
    ↓
Apply worker_skill_roster overrides
    ↓
Build working_hours_df per modality
    ↓
Real-time assignment with load balancing

---

## Key Features

### Smart Load Balancing
- **Skill-based routing** with configurable exclusion rules
- **Work-hour adjusted ratios** ensure fair distribution
- **Two-level fallback** system for high availability
- See [CONFIGURATION.md](docs/CONFIGURATION.md) for routing details

### Skill System
| Value | Name | Behavior |
|-------|------|----------|
| **w** | Weighted | Assisted/learning worker - uses additional W modifier stream |
| **1** | Active | Primary routing - actively performs this skill (shift load modifier applies) |
| **0** | Passive | Fallback only - can help if needed |
| **-1** | Excluded | Never assigned - cannot do this skill |

### Weighting System
Assignments are weighted by:
- **Skill weight**: e.g., Notfall=1.1, Privat=1.2
- **Modality factor**: e.g., MR=1.2, XRAY=0.33
- **Shift load modifier**: Per-shift multiplier from schedule rows (applied to all assignments)
- **Weighted modifier**: Worker-level multiplier for `w` assignments
- **Skill×Modality overrides**: Custom weights for specific combinations

Where each control lives:
- **Shift load modifier**: `/prep-today` and `/prep-tomorrow` (Change/Prep pages)
- **W modifier**: `/skill-roster` (Skill Matrix page)
- **Skill×Modality matrix**: `/button-weights` (Weight Matrix page)

### Admin Pages
1. **Skill Matrix** (`/skill-roster`) - Edit worker skills across modalities (saves directly)
2. **Schedule Edit (Today)** (`/prep-today`) - Modify today (live)
3. **Schedule Edit (Tomorrow)** (`/prep-tomorrow`) - Prepare tomorrow (staged)
4. **Weight Matrix** (`/button-weights`) - Configure button weights and special task weights
5. **Balance** (`/worker-load`) - Simple summary, Advanced matrix, Flow chart

### Navigation & UI Features

**Cortex layout** - Unified navigation across all pages:
- **Dashboard** (`/`) - Main workload view (toggle Modality/Skill views)
- **Timetable** (`/timetable`) - Visual timeline of shifts and gaps
- **Skill Matrix** (`/skill-roster`) - Manage worker skills (direct save)
- **Change Today** (`/prep-today`) - Live edits for today
- **Prep Tomorrow** (`/prep-tomorrow`) - Staged edits for tomorrow
- **Worker Load** (`/worker-load`) - Balance dashboard with `Simple`, `Advanced`, and `Flow` modes
- **Weight Matrix** (`/button-weights`) - Configure button and special task weights
- **Admin** (`/upload`) - Master CSV upload, MedSpace export link, and `HARD RELOAD TODAY`

### Master CSV Semantics

- Uploading a new Master CSV updates only the stored source file.
- It does **not** overwrite an already staged `Prep Tomorrow` plan.
- To refresh staged tomorrow data from a newly uploaded CSV, run `Prep Tomorrow` again for the selected target date.
- `HARD RELOAD TODAY` rebuilds only the current live day from the current Master CSV and resets counters.

---

## Project Structure

```
RadIMO_Cortex/
├── app.py                      # Main entry point (Flask app)
├── routes.py                   # Route and API definitions
├── balancer.py                 # Load balancing logic
├── config.py                   # Config loader and normalization
├── config.yaml                 # Configuration (mapping, skills, special tasks)
├── requirements.txt            # Python dependencies
├── gunicorn_config.py          # Gunicorn server configuration
├── data/                       # Persistent data files (auto-created)
│   ├── worker_skill_roster.json  # Worker skill roster
│   ├── button_weights.json       # Button weights for skills/special tasks
│   ├── fairness_state.json       # Application state persistence
│   └── backups/                  # Automatic backups (rotated, n=5)
│       ├── worker_skill_roster_*.json
│       ├── button_weights_*.json
│       └── fairness_state_*.json
├── uploads/                    # Runtime schedule data
│   └── backups/                # Schedule backups (staged/live/scheduled)
├── logs/                       # Application logs and usage stats
│   ├── selection.log           # Assignment + system log
│   └── usage_stats/            # Usage logging exports
│       └── usage_stats.csv     # Daily usage rows (wide format)
├── data_manager/               # Data handling and state management
│   ├── __init__.py              # Package exports
│   ├── csv_parser.py            # CSV parsing utilities
│   ├── file_ops.py              # File handling helpers
│   ├── json_manager.py          # Centralized JSON file management
│   ├── schedule_crud.py         # Schedule create/update/delete
│   ├── scheduled_tasks.py       # Scheduled jobs and timers
│   ├── state_persistence.py     # Save/load system state
│   └── worker_management.py     # Worker roster management
├── lib/                        # Library modules
│   ├── utils.py                # Utility functions and logging
│   └── usage_logger.py         # Usage tracking
├── scripts/                    # Development and utility scripts
│   ├── ops_check.py            # Pre-deployment checks
│   └── gen_test_data.py        # Scenario generator for deterministic test data
│   ├── apply_demo_data.py      # Prepare demo CSV + demo weights + load/preload
│   └── capture_screenshots.py  # Playwright screenshots for main pages
├── test_data/                  # Test and demo data
│   ├── demo/                   # Shared demo fixtures (e.g. button weights)
│   └── generated/              # Scenario-generated deterministic fixtures
├── templates/                  # HTML templates (Admin pages aligned to Prep)
├── static/                     # CSS, JS, assets
│   ├── EULA.txt                 # Licensing terms
│   └── verfahrensverzeichniss.txt # GDPR documentation (German)
└── docs/                       # Documentation
    ├── ADMIN_GUIDE.md          # Admin pages guide
    ├── API.md                  # API endpoints
    ├── CONFIGURATION.md        # Config reference (incl. special tasks)
    ├── SCREENSHOTS.md          # Screenshot generation for training docs
    ├── USAGE_LOGGING.md        # Usage logging documentation
    └── WORKFLOW.md             # Master CSV workflow guide
```

---

## Documentation

| Document | Description |
|----------|-------------|
| [WORKFLOW.md](docs/WORKFLOW.md) | Medweb CSV workflow, upload strategies |
| [CONFIGURATION.md](docs/CONFIGURATION.md) | Full config.yaml reference |
| [API.md](docs/API.md) | REST API endpoints |
| [ADMIN_GUIDE.md](docs/ADMIN_GUIDE.md) | Admin pages and skill roster |
| [USAGE_LOGGING.md](docs/USAGE_LOGGING.md) | Usage statistics and export workflow |
| [TEST_DATA.md](docs/TEST_DATA.md) | Scenario-based generated test data workflow |
| [SCREENSHOTS.md](docs/SCREENSHOTS.md) | Training screenshot workflow and scene catalog |

---

## Operational Checks

Run system health checks:

```bash
python scripts/ops_check.py
```

Validates: config file, admin password, upload folder, modalities, skills, medweb mapping rules.

---

## Security

- **Admin password**: Configure in `config.yaml` (enforced when `admin_access_protection_enabled` is true)
- **Access password**: Optional access login for non-admin pages (`access_protection_enabled`)
- **Session-based auth**: Admin routes protected by login when enabled
- **GDPR-compliant**: Documentation in `static/verfahrensverzeichniss.txt`

---

## Version

**RadIMO Cortex v20** - Current production version

For more information, see [EULA.txt](static/EULA.txt) or contact **Dr. M. Russe**.

---

**Made for radiology teams**
