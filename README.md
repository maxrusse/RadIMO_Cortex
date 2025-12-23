# RadIMO Cortex

**Intelligent Radiology Orchestration**

Smart worker assignment platform for radiology teams with automatic load balancing, skill-aware routing, and shift-based fairness.

---

## What is RadIMO Cortex?

RadIMO Cortex orchestrates workload distribution for radiology teams across multiple modalities (CT, MR, XRAY) and skills (Normal, Notfall, Privat, Herz, Msk, Chest). It automatically balances assignments to ensure fair distribution while respecting worker availability, shift timing, and skill levels.

**Key Capabilities:**
- Real-time worker assignment with automatic load balancing
- Skill-based routing with configurable exclusion rules
- Dynamic shift handling with work-hour-adjusted balancing
- Two UI modes: by modality or by skill
- Two-level fallback for high availability
- Master CSV integration for monthly schedule management
- Admin system: Skill Matrix (direct save), Schedule Edit (Today + Prep Tomorrow)
- Worker skill roster admin portal with simplified JSON management
- GAP handling (split shifts) for meetings and boards
- Overnight shift handling across midnight boundaries
- Smart skill filtering on Schedule Edit and Timetable views

---

## Quick Start

### Installation

```bash
pip install -r requirements.txt
python scripts/ops_check.py  # Check system readiness
flask --app app run --debug  # Start application
```

### Access Points

**Operational Pages (Public):**
| Page | URL | Description |
|------|-----|-------------|
| Main Interface | `/` | Assignment by modality (CT/MR/XRAY) |
| Skill View | `/by-skill` | Assignment by skill (Normal/Notfall/Herz/etc.) |
| Timetable | `/timetable` | Visualize shifts and schedules |

**Admin Pages (Password Protected):**
| Page | URL | Description |
|------|-----|-------------|
| Admin Panel | `/upload` | Master CSV management, stats, system health |
| Skill Matrix | `/skill-roster` | Edit worker skills (Direct Save) |
| Schedule Edit | `/prep-next-day` | Edit Today (Live) or Prep Tomorrow (Staged) |

---

## Core Workflow

Master CSV (monthly schedule)
    ↓
Upload via /upload (Master CSV)
    ↓
Load Today (Live) or Preload Tomorrow (Staged)
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
| **w** | Weighted | Visual marker for weighted entries (Modifier controls load) |
| **1** | Active | Primary routing - actively performs this skill |
| **0** | Passive | Fallback only - can help if needed |
| **-1** | Excluded | Never assigned - cannot do this skill |

### Weighting System
Assignments are weighted by:
- **Skill weight**: e.g., Notfall=1.1, Privat=1.2
- **Modality factor**: e.g., MR=1.2, XRAY=0.33
- **Worker modifier**: Individual multiplier
- **Skill×Modality overrides**: Custom weights for specific combinations

### Admin Pages
1. **Skill Matrix** (`/skill-roster`) - Edit worker skills across modalities (saves directly)
2. **Schedule Edit** (`/prep-next-day`) - Modify Today (Live) or prepare Tomorrow (Staged)

### Navigation & UI Features

**Cortex Layout** - Unified navigation across all pages:
- **Dashboard** (`/`) - Main workload view (toggle Modality/Skill views)
- **Timetable** (`/timetable`) - Visual timeline of shifts and gaps
- **Skill Matrix** (`/skill-roster`) - Manage worker skills (direct save)
- **Schedule Edit** (`/prep-next-day`) - Live Edit (Today) + Prep Tomorrow (Staged)
- **Admin** (`/upload`) - System configuration and CSV uploads

---

## Project Structure

```
RadIMO_Cortex/
├── app.py                      # Main entry point (Flask app)
├── routes.py                   # Route and API definitions
├── data_manager.py             # Data handling and state management
├── balancer.py                 # Load balancing logic
├── config.py                   # Config loader and normalization
├── config.yaml                 # Configuration (mapping, skills, weights)
├── worker_skill_roster.json    # Worker skill roster (persistent)
├── requirements.txt            # Python dependencies
├── gunicorn_config.py          # Gunicorn server configuration
├── lib/                        # Library modules
│   ├── utils.py                # Utility functions and logging
│   └── usage_logger.py         # Usage tracking
├── scripts/                    # Development and utility scripts
│   ├── ops_check.py            # Pre-deployment checks
│   ├── prepare_config.py       # Config generator from CSV
│   └── code_aggregator.py      # Documentation export tool
├── test_data/                  # Test CSV files and examples
├── templates/                  # HTML templates (Admin pages aligned to Prep)
├── static/                     # CSS, JS, assets
├── uploads/                    # Master CSV and backups storage
└── docs/                       # Documentation
    ├── WORKFLOW.md             # Master CSV workflow guide
    ├── CONFIGURATION.md        # Config reference
    ├── API.md                  # API endpoints
    ├── ADMIN_GUIDE.md          # Admin pages guide
    └── USAGE_LOGGING.md        # Usage logging documentation
```

---

## Documentation

| Document | Description |
|----------|-------------|
| [WORKFLOW.md](docs/WORKFLOW.md) | Medweb CSV workflow, upload strategies |
| [CONFIGURATION.md](docs/CONFIGURATION.md) | Full config.yaml reference |
| [API.md](docs/API.md) | REST API endpoints |
| [ADMIN_GUIDE.md](docs/ADMIN_GUIDE.md) | Admin pages and skill roster |

---

## Operational Checks

Run system health checks:

```bash
python scripts/ops_check.py
```

Validates: config file, admin password, upload folder, modalities, skills, medweb mapping rules.

---

## Security

- **Admin password**: Configure in `config.yaml`
- **Session-based auth**: Admin routes protected by login
- **GDPR-compliant**: Documentation in `static/verfahrensverzeichniss.txt`

---

## Version

**RadIMO Cortex v20** - Current production version

For more information, see [EULA.txt](static/EULA.txt) or contact **Dr. M. Russe**.

---

**Made for radiology teams**
