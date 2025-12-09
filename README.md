# RadIMO Cortex

**Intelligent Radiology Orchestration**

Smart worker assignment platform for radiology teams with automatic load balancing, skill-aware routing, and shift-based fairness.

---

## What is RadIMO Cortex?

RadIMO Cortex orchestrates workload distribution for radiology teams across multiple modalities (CT, MR, XRAY) and skills (Normal, Notfall, Privat, Herz, Msk, Chest). It automatically balances assignments to ensure fair distribution while respecting worker availability, shift timing, and skill levels.

**Key Capabilities:**
- Real-time worker assignment with automatic load balancing
- Smart fallback system with availability and fairness triggers
- Dynamic shift handling with work-hour-adjusted balancing
- Two UI modes: by modality or by skill
- Pool-based selection across skills and modalities
- Config-driven medweb CSV integration with automated daily preload
- Three-page admin system: Planning (staged), Prep (tomorrow), Day Control (immediate)
- Worker skill roster admin portal with JSON-based staged/active workflow
- Time exclusion system for boards, meetings, and teaching activities
- Overnight shift handling across midnight boundaries
- Smart skill filtering on Day Control and Timetable views

---

## Quick Start

### Installation

```bash
pip install -r requirements.txt
python ops_check.py          # Check system readiness
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
| Admin Panel | `/upload` | Upload medweb CSV, system management |
| Skill Matrix | `/skill_roster` | Plan skill changes (STAGED mode) |
| Prep Next Day | `/prep-next-day` | Prepare tomorrow's schedule |
| Day Control | `/admin/live-edit` | Emergency same-day edits (immediate effect) |

---

## Core Workflow

```
medweb.csv (monthly schedule)
    ↓
Upload via /upload (manual) or auto-preload at 7:30 AM
    ↓
Config-driven parsing (medweb_mapping rules)
    ↓
Apply worker_skill_roster overrides
    ↓
Build working_hours_df per modality
    ↓
Real-time assignment with load balancing
```

---

## Key Features

### Smart Exclusion-Based Routing

RadIMO uses exclusion-based selection to ensure fair workload distribution across all workers while respecting specialty boundaries:

**How It Works:**
1. **Primary Pool**: Start with ALL available workers across all skills
2. **Apply Exclusions**: Remove workers with excluded skills (e.g., Chest specialists don't get Herz work)
3. **Calculate Ratios**: Weighted assignments / hours worked for each candidate
4. **Select Best**: Worker with lowest workload ratio

**Two-Level Fallback:**
1. **Level 1** (Exclusion-based): ALL workers EXCEPT those with excluded skills=1
2. **Level 2** (Skill-based fallback): Workers with requested skill≥0 (ignores exclusions)
3. **Level 3**: No assignment possible

**Skill Values:**
- skill=1 (Active): Actively performs this skill
- skill=0 (Passive): Can do this skill if needed (training, backup)
- skill=-1 (Excluded): Cannot do this skill

**Configuration Example:**
```yaml
exclusion_rules:
  Herz:
    exclude_skills: [Chest, Msk]  # Chest/Msk specialists don't get Herz work
```

**Example Workflow:**
- Request: Herz work needed
- Level 1: Try ALL workers EXCEPT those with Chest=1 or Msk=1 → Pick lowest ratio
- Level 2 (if Level 1 empty): Try workers with Herz≥0 → Pick lowest ratio
- Level 3: No assignment

### Skill System
| Value | Name | Behavior |
|-------|------|----------|
| **1** | Active | Primary requests + fallback |
| **0** | Passive | Fallback only (training, backup) |
| **-1** | Excluded | Not available |

### Weighting System
Assignments are weighted by:
- **Skill weight**: e.g., Notfall=1.1, Privat=1.2
- **Modality factor**: e.g., MR=1.2, XRAY=0.33
- **Worker modifier**: Individual multiplier
- **Skill×Modality overrides**: Custom weights for specific combinations

### Three-Page Admin System
1. **Skill Matrix** (`/skill_roster`) - Plan skill changes, staged before activation
2. **Prep Next Day** (`/prep-next-day`) - Prepare tomorrow's schedule
3. **Day Control** (`/admin/live-edit`) - Emergency same-day changes (immediate effect)

### Navigation & UI Features

**Cortex Layout** - Unified navigation across all pages:
- **Dashboard** - Main workload view (toggle between Modality/Skill views)
- **Timetable** - Visual timeline of shifts and schedules
- **Skill Matrix** - Manage worker skills (staged changes)
- **Day Control** - Emergency same-day overrides (immediate effect)
- **Admin** - System configuration and CSV uploads

**Smart Skill Filtering:**
- **Day Control** (`/admin/live-edit`) - Filter worker tables by active skill
  - Click "All" to show all workers
  - Click skill name (Normal, Notfall, Herz, etc.) to show only workers with that skill active (value=1)
  - Separate filters for CT, MR, and XRAY tables
- **Timetable** (`/timetable`) - Filter timetable view by active skill
  - Same filtering logic as Day Control
  - Timetable dynamically rebuilds with filtered workers
  - Allows sub-specialty leads to focus on their team

---

## Project Structure

```
RadIMO_Cortex/
├── app.py                      # Main Flask application
├── config.yaml                 # Configuration (mapping, skills, weights)
├── worker_skill_overrides.json # Worker skill roster (admin portal)
├── ops_check.py                # Pre-deployment checks
├── requirements.txt            # Python dependencies
├── templates/                  # HTML templates
├── static/                     # CSS, JS, assets
├── uploads/                    # Medweb CSV storage
└── docs/                       # Documentation
    ├── WORKFLOW.md             # CSV workflow guide
    ├── CONFIGURATION.md        # Config reference
    ├── API.md                  # API endpoints
    └── ADMIN_GUIDE.md          # Admin pages guide
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
python ops_check.py
```

Validates: config file, admin password, upload folder, modalities, skills, medweb mapping rules.

---

## Security

- **Admin password**: Configure in `config.yaml`
- **Session-based auth**: Admin routes protected by login
- **GDPR-compliant**: Documentation in `static/verfahrensverzeichniss.txt`

---

## Version

**RadIMO v19** - Current production version

For more information, see [EULA.txt](static/EULA.txt) or contact **Dr. M. Russe**.

---

**Made for radiology teams**
