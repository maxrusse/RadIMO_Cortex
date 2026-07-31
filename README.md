# RadIMO Cortex

**Intelligent Radiology Orchestration**

Worker assignment for radiology teams with automatic load balancing, skill-aware routing, and shift-based fairness.

---

## What is RadIMO Cortex?

RadIMO Cortex orchestrates workload distribution for radiology teams across CT, MR, and X-ray using skills such as Notfall, Privat, Gyn, AOU, CVT, MDH, and Kinder. It balances assignments for fairness while respecting availability, shift timing, and skill levels.

**Key capabilities:**
- Real-time worker assignment with automatic load balancing
- Skill-based routing with configurable exclusion rules
- Dynamic shift handling with work-hour-adjusted balancing
- Two UI modes: by modality or by skill
- Two-level fallback for high availability
- Master CSV integration for monthly schedule management
- Admin system for skills, live-day changes, next-day planning, corrections, weights, files, logs, and settings
- Worker skill roster admin portal with simplified JSON management
- GAP handling (split shifts) for meetings and boards
- Smart skill filtering on planning and Schedule views
- Special tasks for custom sub-workflows with separate tracking
- Recurring synthetic shift workers defined in config for summary roles
- Shared timeline rendering for timetable + prep/change pages

---

## Quick Start

### Installation

```bash
pip install -r requirements.txt
cp config.demo.yaml config.yaml  # First checkout only; set live credentials locally
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
| Live | `/` | Assignment by modality (CT/MR/X-ray) |
| Skill View | `/by-skill` | Assignment by skill (Notfall, CVT, MDH, etc.) |
| Schedule | `/timetable` | Visualize shifts and gaps |

If basic access protection is enabled, users authenticate via `/access-login` before reaching the operational pages.
Admin pages require a session via `/login` when `admin_access_protection_enabled` is true.

**Admin pages (password protected when enabled):**
| Page | URL | Description |
|------|-----|-------------|
| Analysis | `/performance` | Management-level balance overview |
| Workload | `/worker-load` | Detailed load monitoring |
| Today | `/prep-today` | Edit the current live schedule |
| Planning | `/prep-tomorrow` | Prepare a staged workday |
| Corrections | `/manual-adjustments` | Publish manual load corrections |
| Skills | `/skill-roster` | Edit worker skills |
| Weights | `/button-weights` | Configure button and special-task weights |
| Import | `/upload` | Upload Master CSV and run `HARD RELOAD TODAY` |
| Tools | `/admin/tools` | Settings, files, logs, readiness, and runtime reload |

---

## Core Workflow

Master CSV (current source file)
    ↓
Upload via /upload (Master CSV)
    ↓
HARD RELOAD TODAY (live) or Planning reload (staged)
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
- **Modality factor**: e.g., MR=1.2, X-ray=0.33
- **Shift load modifier**: Per-shift multiplier from schedule rows (applied to all assignments)
- **Weighted modifier**: Worker-level multiplier for `w` assignments
- **Skill×Modality overrides**: Custom weights for specific combinations

Where each control lives:
- **Shift load modifier**: `/prep-today` and `/prep-tomorrow` (Change/Prep pages)
- **W modifier**: `/skill-roster` (Skills page)
- **Skill×Modality matrix**: `/button-weights` (Weights page)

### Admin Pages
1. **Analysis** (`/performance`) - Management overview
2. **Workload** (`/worker-load`) - Simple summary, advanced matrix, and flow chart
3. **Today / Planning** (`/prep-today`, `/prep-tomorrow`) - Live and staged schedule editing
4. **Corrections** (`/manual-adjustments`) - Manual load adjustments
5. **Skills / Weights** (`/skill-roster`, `/button-weights`) - Worker capabilities and routing weights
6. **Import / Tools** (`/upload`, `/admin/tools`) - Source data and operations

### Navigation & UI Features

**Cortex layout** - Unified navigation across all pages:
- **Live** (`/`) - Main assignment view with modality/skill toggle
- **Schedule** (`/timetable`) - Visual timeline of shifts and gaps
- **Skills** (`/skill-roster`) - Manage worker capabilities
- **Today** (`/prep-today`) - Live edits for the current day
- **Planning** (`/prep-tomorrow`) - Staged edits for a selected workday
- **Workload** (`/worker-load`) - Detailed balance views
- **Weights** (`/button-weights`) - Configure button and special-task weights
- **Import** (`/upload`) - Master CSV upload and `HARD RELOAD TODAY`
- **Tools** (`/admin/tools`) - Settings, files, logs, status, and runtime operations

### Master CSV Semantics

- Uploading a new Master CSV updates only the stored source file.
- It does **not** overwrite an already staged Planning snapshot.
- To refresh staged data from a newly uploaded CSV, run Planning again for the selected target date.
- `HARD RELOAD TODAY` rebuilds only the current live day from the current Master CSV and resets counters.

---

## Project Structure

```
RadIMO_Cortex/
├── app.py                      # Main entry point (Flask app)
├── routes.py                   # Route and API definitions
├── balancer.py                 # Load balancing logic
├── config.py                   # Config loader and normalization
├── config.demo.yaml            # Tracked demo configuration; passwords are non-secret demo values
├── config.yaml                 # Ignored deployment configuration created from the demo file
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
│   ├── __init__.py              # Initialized shared state only
│   ├── csv_parser.py            # CSV parsing utilities
│   ├── file_ops.py              # File handling helpers
│   ├── json_manager.py          # Centralized JSON file management
│   ├── schedule_crud.py         # Atomic row, worker-plan, and gap-batch updates
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
    ├── INSTALL_UBUNTU.md       # Ubuntu installation and service setup
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
| [INSTALL_UBUNTU.md](docs/INSTALL_UBUNTU.md) | Ubuntu server installation and intranet deployment guide |
| [HANDOVER.txt](docs/HANDOVER.txt) | Operational handover, restart, reset, and incident response notes |
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

- **Local configuration**: Copy `config.demo.yaml` to the ignored `config.yaml`; never commit live credentials
- **Admin password**: Replace the demo value in `config.yaml` before live use (enforced when `admin_access_protection_enabled` is true)
- **Access password**: Optional access login for non-admin pages (`access_protection_enabled`)
- **Session-based auth**: Admin routes protected by login when enabled
- **GDPR-compliant**: Documentation in `static/verfahrensverzeichniss.txt`

---

## Version

**RadIMO Cortex v20** - Current production version

For more information, see [EULA.txt](static/EULA.txt) or contact **Dr. M. Russe**.

---

**Made for radiology teams**
