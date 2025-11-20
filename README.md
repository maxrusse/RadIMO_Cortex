# RadIMO SBZ - Radiology Workload Coordinator

**Radiology: Innovation, Management & Orchestration**

Smart worker assignment system for radiology teams with automatic load balancing, flexible fallback strategies, and config-driven medweb CSV integration.

---

## 🎯 What is RadIMO SBZ?

RadIMO orchestrates workload distribution for radiology teams across multiple modalities (CT, MR, XRAY) and skills (Normal, Notfall, Privat, Herz, Msk, Chest). It automatically balances assignments to ensure fair distribution while respecting worker availability and skill levels.

**Key Capabilities:**
- 📊 Real-time worker assignment with automatic load balancing
- 🔄 Smart fallback strategies for overload situations
- ⏰ Dynamic shift handling with work-hour-adjusted balancing
- 📱 Two UI modes: by modality or by skill
- 📈 Cross-modality workload tracking and overflow management
- 🔮 **Config-driven medweb CSV integration** with automated daily preload
- 📋 **Three-page admin system**: Planning (staged), Prep (tomorrow), Live Edit (immediate)
- ⚙️ **Worker skill roster admin portal** with JSON-based staged/active workflow
- ⏱️ **Time exclusion system** for boards, meetings, and teaching activities

---

## 📊 High-Level System Overview (For Presentations)

### The Problem
Radiology departments face complex daily staffing challenges:
- **Multiple modalities** require specialized coverage (CT, MR, X-ray)
- **Variable skills** within teams (emergency, cardiac, MSK specialists)
- **Changing schedules** with rotations, meetings, and boards
- **Fair workload distribution** across overlapping shifts
- **Real-time coordination** needed to match workers to incoming studies

Traditional manual assignment leads to:
- ❌ Overloading of experienced staff
- ❌ Inefficient use of specialist skills
- ❌ No visibility into cross-modality workload
- ❌ Time-consuming schedule preparation

### The Solution: RadIMO SBZ

RadIMO is an **intelligent workload orchestration system** that automates fair worker assignment while respecting expertise, availability, and rotation schedules.

**Core Workflow:**
```
Medical Scheduling System (medweb)
        ↓
Export monthly CSV with all worker activities
        ↓
RadIMO Import (one-time upload + daily auto-refresh at 7:30 AM)
        ↓
Intelligent Parsing:
  • Activity → Modality mapping (e.g., "CT Spätdienst" → CT evening shift)
  • Automatic skill assignment based on activity patterns
  • Time exclusions for boards/meetings (auto-splits shifts)
  • Worker-specific skill overrides for specialists
        ↓
Real-Time Assignment Engine (web interface)
  • Coordinator requests: "Need CT cardiac specialist"
  • System selects least-loaded qualified worker
  • Updates counters, tracks fairness metrics
  • Supports cross-modality overflow automatically
        ↓
Result: Fair distribution, specialist utilization, real-time visibility
```

### Key Innovation: Config-Driven Intelligence

**Before RadIMO:**
- Manual Excel file creation per modality
- Static schedules with no real-time adaptation
- No automatic fairness balancing
- Separate tools for tracking and assignment

**With RadIMO v18:**
- **Single CSV source** from existing medweb system
- **Configuration-based mapping** (add new activities without coding)
- **Automatic daily updates** (7:30 AM refresh)
- **Real-time fairness engine** (work-hour-adjusted balancing)
- **Intelligent fallback** (finds qualified alternatives automatically)
- **Admin portal for skill management** (update worker qualifications in seconds)

### Concrete Example

**Scenario:** It's 2 PM on Tuesday. CT is swamped, needs cardiac specialist.

**RadIMO's Decision Process:**
1. **Request:** Coordinator clicks "CT → Herz (Cardiac)" button
2. **Check availability:**
   - Dr. Müller: On shift, Herz=1 (active), ratio=2.1 (10 cases / 4.7 hours worked)
   - Dr. Schmidt: On shift, Herz=1 (active), ratio=1.8 (9 cases / 5.0 hours worked)
   - Dr. Weber: On shift, Herz=0 (fallback only), ratio=1.5
3. **Apply rules:**
   - Dr. Weber excluded (Herz=0 means passive, only for overflow)
   - Dr. Schmidt has lower ratio → selected (less loaded per hour worked)
4. **Fallback if needed:**
   - If both at max capacity → try Herz in MR/X-ray
   - If no Herz available → fallback to Notfall → Normal
5. **Update & track:**
   - Dr. Schmidt counter +1
   - Global stats updated
   - Fairness metrics recalculated

**Result:** Dr. Schmidt assigned, fair distribution maintained automatically.

### Time Exclusion Innovation

**Problem:** Workers need time for boards, meetings, teaching during their shift
- Traditional: Create multiple schedule entries (before/after meeting)
- RadIMO: Automatic shift splitting based on weekday schedules

**Example:**
```yaml
# Config: Tuesday board 15:00-17:00 with 30min prep
medweb_mapping:
  rules:
    - match: "Kopf-Hals-Board"
      exclusion: true
      schedule:
        Dienstag: "15:00-17:00"  # Tuesday only
      prep_time:
        before: "30m"             # Prep starts 14:30

# CSV: Dr. Müller has "Kopf-Hals-Board" + regular CT shift (07:00-21:00)

# RadIMO automatically creates:
Shift 1: 07:00-14:30  (available for assignments)
EXCLUDED: 14:30-17:00  (board + prep time)
Shift 2: 17:00-21:00  (available for assignments)
```

**Benefits:**
- ✅ Day-specific rules (same board, different times per weekday)
- ✅ No manual CSV editing needed
- ✅ Prep time automatically added
- ✅ Multiple exclusions per worker supported

### Three-Page Admin System

RadIMO provides three distinct admin interfaces for different operational needs:

#### 1. 📋 **Skill Roster** (`/skill_roster`) - Planning Mode

**Purpose:** Plan worker skill changes for rotations and long-term scheduling
- Changes are **STAGED** - no immediate effect on current assignments
- Edit values: -1 (excluded), 0 (fallback), 1 (active)
- Click "Save to Staging" → saves to `worker_skill_overrides_staged.json`
- Click "Activate Changes" → applies staged changes to active roster
- Perfect for: Weekly rotation planning, training certifications, scheduled changes

**Use Case:**
1. Go to `/skill_roster` (admin password protected)
2. Find worker "AAn" in table
3. Change MSK from 0 → 1 (MSK rotation starts next week)
4. Click "Save to Staging" - **no immediate effect**
5. When ready: Click "Activate Changes" - **now applied to assignments**

#### 2. 📝 **Prep Next Day** (`/prep-next-day`) - Tomorrow's Schedule

**Purpose:** Prepare and preview tomorrow's worker schedule
- Upload new medweb CSV for next day
- Simple mode: Upload CSV, let system auto-parse
- Advanced mode: Edit individual workers, adjust times, modify skills
- Changes affect **tomorrow's date only** - no impact on today
- Perfect for: Daily schedule preparation, next-day corrections

#### 3. ⚠️ **Live Edit** (`/admin/live-edit`) - Emergency Same-Day Changes

**Purpose:** Make immediate changes to current day's assignments
- Changes take effect **IMMEDIATELY** - no staging
- Edit worker hours, names, skills, modifiers
- Delete worker entries
- Modality tabs (CT/MR/XRAY) for organized editing
- Big warning banners about immediate impact
- Perfect for: Emergency substitutions, last-minute schedule changes, same-day corrections

**⚠️ WARNING:** Use Live Edit with caution - changes are instant!

### Workflow Separation

```
┌──────────────────────────────────────────────────────────┐
│  PLANNING (Future)          Skill Roster                 │
│  ├─ Staged changes          (Planning Mode)              │
│  ├─ Review before apply                                  │
│  └─ Activate when ready                                  │
├──────────────────────────────────────────────────────────┤
│  PREP (Tomorrow)            Prep Next Day                │
│  ├─ Upload CSV for next day                              │
│  ├─ Preview and adjust                                   │
│  └─ No effect on current day                             │
├──────────────────────────────────────────────────────────┤
│  OPERATIONAL (Now)          Live Edit                    │
│  ├─ Immediate effect        (DANGER ZONE)               │
│  ├─ Emergency changes only                               │
│  └─ Careful: impacts ongoing assignments                 │
└──────────────────────────────────────────────────────────┘
```

### Business Value

**Efficiency Gains:**
- ⏱️ **Setup time:** 5 minutes monthly (CSV upload) vs. daily Excel editing
- ⏱️ **Assignment time:** 2 seconds automated vs. 30+ seconds manual coordination
- ⏱️ **Schedule updates:** Real-time via web portal vs. file editing + restart

**Quality Improvements:**
- 📊 **Fair distribution:** Automatic work-hour-adjusted balancing
- 🎯 **Specialist utilization:** Intelligent skill matching with fallback
- 👁️ **Visibility:** Real-time dashboards show workload across all modalities
- 🔄 **Adaptability:** Handles rotations, meetings, overflow automatically

**Risk Reduction:**
- ✅ Single source of truth (medweb CSV)
- ✅ Configuration version control (Git-tracked)
- ✅ Audit trail in logs (who assigned what, when)
- ✅ GDPR-compliant (documented in verfahrensverzeichniss.txt)

### Technical Highlights

**Modern Stack:**
- **Backend:** Python Flask with APScheduler for automation
- **Frontend:** Vanilla JavaScript (no heavy frameworks)
- **Data:** Pandas for CSV processing, JSON for runtime config
- **Deployment:** Gunicorn + systemd, runs on local network

**Scalability:**
- Handles 50+ workers across 3 modalities
- Thousands of daily assignments
- Sub-second response times
- Minimal resource footprint

**Maintainability:**
- Config-driven (90% of changes need no code)
- Comprehensive documentation (5 detailed guides)
- Operational health checks (ops_check.py)
- Clear separation: config.yaml (static), JSON (dynamic)

---

## 🚀 Quick Start

### Installation

```bash
# Install dependencies
pip install -r requirements.txt

# Check system readiness
python ops_check.py

# Start the application
flask --app app run --debug
```

### Access Points

**Operational Pages (Public):**
- **Main Interface**: `http://localhost:5000/` - By modality view (CT/MR/XRAY)
- **Skill View**: `http://localhost:5000/by-skill` - By skill view (Normal/Notfall/Herz/etc.)
- **Timeline**: `http://localhost:5000/timetable` - Visualize shifts and schedules

**Admin Pages (Password Protected):**
- **Admin Panel**: `http://localhost:5000/upload` - Upload medweb CSV & system management hub
- **Skill Roster**: `http://localhost:5000/skill_roster` - Plan skill changes (STAGED mode)
- **Prep Next Day**: `http://localhost:5000/prep-next-day` - Prepare tomorrow's schedule
- **Live Edit**: `http://localhost:5000/admin/live-edit` - Emergency same-day edits (⚠️ IMMEDIATE EFFECT)

---

## ✨ Key Features

### 1. **Config-Driven Medweb CSV Integration** ⭐ NEW

Directly ingest medweb CSV schedules with configuration-based activity mapping:

```yaml
medweb_mapping:
  rules:
    # Single modality (traditional)
    - match: "CT Spätdienst"
      modality: "ct"
      shift: "Spaetdienst"
      base_skills: {Normal: 1, Notfall: 1, Privat: 0, Herz: 0, Msk: 0, Chest: 0}

    - match: "MR Assistent 1. Monat"
      modality: "mr"
      shift: "Fruehdienst"
      base_skills: {Normal: 1, Notfall: 0, Privat: 0, Herz: 0, Msk: 0, Chest: 0}

    # Multi-modality (sub-specialty teams) - NEW
    - match: "MSK Assistent"
      modalities: ["xray", "ct", "mr"]  # Available in all three modalities
      shift: "Fruehdienst"
      base_skills: {Normal: 0, Notfall: 0, Msk: 1, Privat: 0, Herz: 0, Chest: 0}
```

**Benefits:**
- No manual Excel file creation needed
- Activity → modality/skill mapping in config.yaml
- **Multi-modality support:** Sub-specialty teams across multiple modalities
- Extensible: add new activities by updating config
- Single CSV upload populates all modalities

### 2. **Automatic Daily Preload** ⏰ NEW

System automatically preloads the next workday schedule at **7:30 AM CET**:

- **Auto-preload**: Runs daily via APScheduler
- **Next workday logic**: Friday → Monday, other days → tomorrow
- **Master CSV**: Last uploaded CSV becomes source for auto-preload
- **Seamless workflow**: No manual intervention required

### 3. **Next-Day Schedule Preparation** 📝 NEW

Advanced edit interface for preparing tomorrow's schedule:

**Two Modes:**
- **Simple Mode**: Click any cell to edit inline (spreadsheet-like UX)
- **Advanced Mode**: Add/delete workers, bulk skill operations

**Features:**
- Modality tabs (CT/MR/XRAY) for easy navigation
- Color-coded skill values: 🟢 Active (1), 🟡 Passive (0), 🔴 Excluded (-1)
- Real-time change tracking with batch save
- Auto-recalculate shift durations when times change
- Completely separate from same-day editing (preserves assignment stability)

### 4. **Worker Skill Roster System** 👥 NEW

Per-worker skill overrides with modality-specific configuration:

```yaml
worker_skill_roster:
  AAn:  # Alona Anzalone
    default:
      Msk: 1      # MSK specialist

  AN:  # Andrea Nedelcu
    default:
      Chest: 1    # Chest specialist
    ct:
      Notfall: 0  # Only fallback for CT Notfall
```

**Configuration Precedence**: `worker_skill_roster` > `medweb_mapping` > worker mapping

### 5. **Dual View Modes**

Choose your workflow:

- **By Modality** (default): Navigate by modality (CT/MR/XRAY) → assign by skill
- **By Skill**: Navigate by skill (Normal/Notfall/Herz) → assign by modality

Toggle between views with one click!

### 6. **Smart Load Balancing**

- **Work-hour-adjusted ratios**: Balances workload based on hours worked, not just assignment count
- **Overlapping shift support**: Handles early/late starters fairly
- **30% imbalance threshold**: Automatic fallback when workload becomes unfair
- **Minimum assignments**: Ensures everyone gets at least 5 assignments before overloading others

### 7. **Flexible Fallback Strategies**

Three modes to handle overflow:

| Strategy | Best For | Behavior |
|----------|----------|----------|
| **skill_priority** | Modality expertise | Try all skills in CT before moving to MR |
| **modality_priority** | Skill expertise | Try Herz in all modalities before trying Notfall |
| **pool_priority** | Maximum fairness | Evaluate all options globally, pick least loaded |

Configure in `config.yaml`:
```yaml
balancer:
  fallback_strategy: skill_priority  # or modality_priority, pool_priority
  imbalance_threshold_pct: 30
  min_assignments_per_skill: 5
```

### 8. **Skill Value System**

Fine-tune worker availability:

| Value | Name | Behavior |
|-------|------|----------|
| **1** | Active | Available for primary requests + fallback |
| **0** | Passive | Available ONLY in fallback (training, backup) |
| **-1** | Excluded | NOT available (on leave, restricted) |

---

## 📊 How It Works

### Medweb CSV to Assignment Flow

```
medweb.csv (monthly schedule from medweb)
    ↓
Upload via /upload (manual) or auto-preload at 7:30 AM
    ↓
Config-driven parsing (medweb_mapping rules)
    ↓
Apply worker_skill_roster overrides
    ↓
Build working_hours_df per modality (CT/MR/XRAY)
    ↓
Optional: Edit via /prep-next-day
    ↓
Real-time assignment system (balancer)
    ↓
Request: CT/Herz → Assign worker with lowest ratio
```

### Assignment Flow

```
Request: CT/Herz
    ↓
1. Check available workers (shift times, skill values)
2. Calculate workload ratio = weighted_assignments / hours_worked_so_far
3. Check imbalance (30% threshold)
    ↓
    If balanced: Select worker with lowest ratio
    If imbalanced: Try fallback (Herz → Notfall → Normal)
    ↓
4. Update counters (skill-specific, global, weighted)
5. Return assigned worker
```

### Workload Calculation

```python
# Dynamic ratio adjusted for shift progress
ratio = weighted_assignments / hours_worked_till_now

# Weighted assignments consider:
- Skill weight (Notfall=1.1, Privat=1.2, Normal=1.0, etc.)
- Modality factor (MR=1.2, CT=1.0, XRAY=0.33)
- Worker modifier (individual multipliers from config/CSV)

# Lower ratio = less loaded = selected
```

### Example: Overlapping Shifts

**At 10:00 AM:**
```
Worker A: 07:00-13:00, 10 assignments, 3h worked → ratio = 10/3 = 3.33
Worker B: 09:00-17:00,  7 assignments, 1h worked → ratio = 7/1 = 7.00

→ Worker A selected (lower ratio = less loaded per hour)
```

---

## 🔧 Configuration

### `config.yaml` Structure

```yaml
# Modalities
modalities:
  ct:
    label: CT
    nav_color: '#1a5276'
    factor: 1.0
  mr:
    label: MR
    factor: 1.2
  xray:
    label: XRAY
    factor: 0.33

# Skills
skills:
  Normal:
    weight: 1.0
    optional: false
  Notfall:
    weight: 1.1
    optional: false
  Herz:
    weight: 1.2
    optional: true
    special: true
  Privat:
    weight: 1.2
    optional: true
  Msk:
    weight: 1.1
    optional: true
    special: true
  Chest:
    weight: 1.1
    optional: true
    special: true

# Balancing
balancer:
  enabled: true
  min_assignments_per_skill: 5
  imbalance_threshold_pct: 30
  allow_fallback_on_imbalance: true
  fallback_strategy: skill_priority  # skill_priority | modality_priority | pool_priority

  fallback_chain:
    Normal: []
    Notfall: [Normal]
    Privat: [Normal]
    Herz: [[Notfall, Normal]]  # Parallel fallback
    Msk: [[Notfall, Normal]]
    Chest: [[Notfall, Normal]]

# Modality overflow
modality_fallbacks:
  xray: [[ct, mr]]  # XRAY can borrow from both CT and MR
  ct: [mr]          # CT can borrow from MR
  mr: []            # MR cannot borrow

# Medweb CSV mapping (NEW)
medweb_mapping:
  rules:
    - match: "CT Spätdienst"
      modality: "ct"
      shift: "Spaetdienst"
      base_skills: {Normal: 1, Notfall: 1, Privat: 0, Herz: 0, Msk: 0, Chest: 0}

    - match: "CT Assistent"
      modality: "ct"
      shift: "Fruehdienst"
      base_skills: {Normal: 1, Notfall: 1, Privat: 0, Herz: 0, Msk: 0, Chest: 0}

    - match: "MR Assistent 1. Monat"
      modality: "mr"
      shift: "Fruehdienst"
      base_skills: {Normal: 1, Notfall: 0, Privat: 0, Herz: 0, Msk: 0, Chest: 0}

    - match: "Chir Assistent"
      modality: "xray"  # Chir → xray mapping
      shift: "Fruehdienst"
      base_skills: {Normal: 1, Notfall: 1, Privat: 0, Herz: 0, Msk: 0, Chest: 0}

# Shift times (NEW)
shift_times:
  Fruehdienst:
    default: "07:00-15:00"
    friday: "07:00-13:00"
  Spaetdienst:
    default: "13:00-21:00"
    friday: "13:00-19:00"

# Worker skill roster (NEW)
worker_skill_roster:
  AAn:  # Alona Anzalone
    default:
      Msk: 1      # MSK specialist

  AN:  # Andrea Nedelcu
    default:
      Chest: 1    # Chest specialist
    ct:
      Notfall: 0  # Only fallback for CT Notfall

  DEMO1:
    default:
      Herz: 1     # Cardiac specialist
      Msk: -1     # Never for Msk

  DEMO2:
    default:
      Privat: 1   # Private patients only
      Normal: 0   # Only fallback for Normal

  DEMO3:
    default:
      Notfall: -1  # First month assistant - no Notfall
```

---

## 📡 API Reference

### Worker Assignment

```bash
# Assign with fallback support
GET /api/{modality}/{skill}
Example: curl http://localhost:5000/api/ct/herz

# Strict mode (no fallback)
GET /api/{modality}/{skill}/strict
Example: curl http://localhost:5000/api/ct/herz/strict
```

**Response:**
```json
{
  "Assigned Person": "Dr. Anna Müller (AM)",
  "Draw Time": "14:23:45",
  "Modality": "ct",
  "Requested Skill": "Herz",
  "Used Skill": "Herz",
  "Fallback Used": false
}
```

### Statistics & Status

```bash
# Get live statistics (modality-based view)
GET /api/quick_reload?modality=ct

# Get live statistics (skill-based view)
GET /api/quick_reload?skill=herz
```

### Medweb CSV Upload (NEW)

```bash
# Upload medweb CSV for specific date
POST /upload
Content-Type: multipart/form-data
- file: medweb.csv
- target_date: 2025-11-21

# Preload next workday (Friday → Monday logic)
POST /preload-next-day
Content-Type: multipart/form-data
- file: medweb.csv

# Force refresh today (EMERGENCY - destroys all counters)
POST /force-refresh-today
Content-Type: multipart/form-data
- file: medweb.csv
```

### Next-Day Preparation (NEW)

```bash
# Get current working_hours_df data for all modalities
GET /api/prep-next-day/data

# Update a single worker row
POST /api/prep-next-day/update-row
Content-Type: application/json
{
  "modality": "ct",
  "row_index": 5,
  "updates": {
    "start_time": "08:00",
    "end_time": "16:00",
    "Normal": 1,
    "Notfall": 0
  }
}

# Add a new worker
POST /api/prep-next-day/add-worker
Content-Type: application/json
{
  "modality": "mr",
  "worker_data": {
    "PPL": "Neuer Worker (NW)",
    "start_time": "07:00",
    "end_time": "15:00",
    "Normal": 1,
    "Notfall": 1,
    ...
  }
}

# Delete a worker
POST /api/prep-next-day/delete-worker
Content-Type: application/json
{
  "modality": "xray",
  "row_index": 3
}
```

---

## 📁 Project Structure

```
RadIMO_SBZ_DEV/
├── app.py                      # Main Flask application
├── config.yaml                 # Configuration file (medweb_mapping, roster, etc.)
├── worker_skill_overrides.json # JSON-based worker skill roster (admin portal)
├── ops_check.py               # Pre-deployment checks
├── requirements.txt           # Python dependencies
├── BACKUP.md                  # Rollback procedure for Excel upload code
├── templates/
│   ├── index.html             # By-modality view
│   ├── index_by_skill.html    # By-skill view
│   ├── upload.html            # Admin panel (medweb CSV upload)
│   ├── prep_next_day.html     # Next-day schedule preparation
│   ├── skill_roster.html      # Worker skill roster admin portal (NEW)
│   ├── timetable.html         # Timeline visualization
│   └── login.html             # Authentication
├── static/
│   ├── vis.js                 # Timeline library
│   ├── favicon.ico
│   └── verfahrensverzeichniss.txt  # GDPR compliance documentation
├── uploads/                   # Medweb CSV storage
│   └── master_medweb.csv      # Master CSV for auto-preload
└── docs/                      # Documentation
    ├── SYSTEM_ANALYSIS.md     # Complete technical analysis
    ├── FRONTEND_ARCHITECTURE.md  # UI architecture details
    ├── TESTING_GUIDE.md       # Testing strategies
    ├── WORKFLOW.md            # Complete medweb CSV workflow
    ├── INTEGRATION_COMPARISON.md  # Why config-driven approach
    └── EXCEL_PATH_MIGRATION.md    # Why Excel upload was removed
```

---

## 📖 Documentation

Comprehensive documentation available in the `docs/` folder:

- **[WORKFLOW.md](docs/WORKFLOW.md)** - Complete medweb CSV workflow, upload strategies, prep page usage
- **[SYSTEM_ANALYSIS.md](docs/SYSTEM_ANALYSIS.md)** - Complete system analysis, fallback strategies, balancing algorithms
- **[FRONTEND_ARCHITECTURE.md](docs/FRONTEND_ARCHITECTURE.md)** - UI structure, templates, API integration
- **[TESTING_GUIDE.md](docs/TESTING_GUIDE.md)** - Testing strategies, edge cases, validation
- **[INTEGRATION_COMPARISON.md](docs/INTEGRATION_COMPARISON.md)** - Why config-driven CSV approach was chosen
- **[EXCEL_PATH_MIGRATION.md](docs/EXCEL_PATH_MIGRATION.md)** - Why Excel upload path was removed

---

## 📋 Medweb CSV Format

RadIMO ingests monthly schedules from medweb in CSV format:

### Expected Columns

| Column | Description | Example |
|--------|-------------|---------|
| Datum | Date in DD.MM.YYYY | 20.11.2025 |
| Tageszeit | Day period (ignored) | Tag |
| Personalnummer | Employee number | 12345 |
| Code des Mitarbeiters | Worker abbreviation | AM |
| Name des Mitarbeiters | Worker full name | Dr. Anna Müller |
| Beschreibung der Aktivität | Activity description | CT Spätdienst |

### Activity Mapping

Activities are mapped to modalities and skills via `config.yaml`:

| Activity | Modality/Modalities | Shift | Example Skills |
|----------|----------|-------|----------------|
| CT Assistent | ct | Fruehdienst | Normal=1, Notfall=1 |
| CT Spätdienst | ct | Spaetdienst | Normal=1, Notfall=1 |
| MR Assistent | mr | Fruehdienst | Normal=1, Notfall=1 |
| MR Assistent 1. Monat | mr | Fruehdienst | Normal=1, Notfall=0 |
| Chir Assistent | xray | Fruehdienst | Normal=1, Notfall=1 |
| SBZ: MRT-OA | mr | Fruehdienst | Privat=1 (PP role) |
| **MSK Assistent** | **xray, ct, mr** ⭐ | Fruehdienst | **Msk=1** (sub-specialty team) |
| **Herz Team** | **ct, mr** ⭐ | Fruehdienst | **Herz=1, Notfall=1** |

⭐ **Multi-modality support (NEW):** Sub-specialty teams can be assigned across multiple modalities simultaneously.

Add new activity mappings by updating `medweb_mapping.rules` in `config.yaml`.

**Multi-modality syntax:**
```yaml
# Single modality (traditional)
- match: "CT Assistent"
  modality: "ct"
  base_skills: {Normal: 1, Notfall: 1}

# Multi-modality (sub-specialty teams)
- match: "MSK Assistent"
  modalities: ["xray", "ct", "mr"]  # Available in all three
  base_skills: {Msk: 1, Normal: 0}
```

---

## 🔐 Security

- **Admin password**: Configure in `config.yaml` (change default for production!)
- **Session-based auth**: Admin routes protected by login
- **No user registration**: Simple password-based access

---

## 🚦 Operational Checks

Run system health checks before deployment:

```bash
python ops_check.py
```

**Checks:**
- ✅ Config file validity
- ✅ Admin password configured
- ✅ Upload folder writable
- ✅ Modalities configured
- ✅ Skills configured
- ✅ Medweb mapping rules present
- ✅ Worker data loaded

---

## 💡 Use Cases

### Central Dispatcher Console
Run on modality workstations for real-time assignments by coordinators.

### Operations Analytics
Poll `/api/quick_reload` to feed dashboards showing overflow patterns.

### Cross-Site Coordination
Configure modality fallbacks to point to other campuses for remote coverage.

### Training & Backup Staff
Use passive skill values (0) for workers who can help but shouldn't be primary choice.

### Next-Day Planning
Use prep page to review and adjust tomorrow's schedule before auto-preload activates.

### Emergency Schedule Changes
Use force refresh when significant staffing changes occur mid-day (e.g., half the staff calls in sick).

---

## 🔄 Recent Updates

### v18 (November 2025)
- ✨ **Config-driven medweb CSV integration** - Direct CSV ingestion with mapping rules
- 🔀 **Multi-modality support** - Sub-specialty teams across multiple modalities (e.g., MSK in xray/ct/mr)
- 📋 **Three-page admin system** - Separated planning (staged), prep (tomorrow), and live editing (immediate)
  - **Skill Roster**: Staged changes with activation workflow (planning mode)
  - **Prep Next Day**: Tomorrow's schedule preparation (no current-day impact)
  - **Live Edit**: Emergency same-day edits (immediate effect with warnings)
- ⚖️ **Conditional modifier application** - Optional `modifier_applies_to_active_only` setting (fair fallback behavior)
- ⏰ **Automatic daily preload** - 7:30 AM auto-preload via APScheduler
- 📝 **Next-day schedule preparation** - Advanced edit page with simple/advanced modes
- ⏱️ **Time exclusion system** - Day-specific board/meeting schedules with auto shift-splitting
- 🔄 **Force refresh capability** - Emergency same-day schedule reload
- 🗑️ **Excel upload removal** - Simplified to single CSV-driven workflow
- 📊 **Master CSV pattern** - Last upload becomes source for auto-preload

### v17 (November 2025)
- ✨ Added skill-based navigation view (`/by-skill`)
- 🔧 Implemented work-hour-adjusted ratio balancing for overlapping shifts
- 📊 Enhanced imbalance detection to use dynamic ratios
- ✅ Implemented `run_operational_checks()` for system validation
- 📝 Fixed skill value documentation (corrected -1/0/1 system)

---

## 🔧 Configuration Tips

### Adding a New Activity Type

1. Add rule to `config.yaml`:
```yaml
medweb_mapping:
  rules:
    - match: "Neue Aktivität"
      modality: "ct"
      shift: "Fruehdienst"
      base_skills: {Normal: 1, Notfall: 1, Privat: 0, Herz: 0, Msk: 0, Chest: 0}
```

2. Restart application (no code changes needed!)

### Configuring Worker-Specific Skills

1. Add to `worker_skill_roster` in `config.yaml`:
```yaml
worker_skill_roster:
  NEUID:  # Worker abbreviation
    default:  # Applies to all modalities
      Normal: 1
      Notfall: 1
      Herz: 1      # This worker does Herz
      Msk: -1      # Never for Msk
    mr:            # MR-specific overrides
      Herz: 0      # Only fallback for MR Herz
```

2. Restart application

### Adjusting Shift Times

1. Modify `shift_times` in `config.yaml`:
```yaml
shift_times:
  Fruehdienst:
    default: "07:30-15:30"  # Changed from 07:00-15:00
    friday: "07:30-13:30"
```

2. Restart application

---

## 📄 License & Contact

**RadIMO v18** - Radiology: Innovation, Management & Orchestration

For more information, see [EULA.txt](static/EULA.txt) or contact **Dr. M. Russe**.

---

## 🤝 Contributing

This is a specialized medical workload distribution system. For questions or suggestions:

1. Review the [Complete Workflow](docs/WORKFLOW.md) documentation
2. Check the [System Analysis](docs/SYSTEM_ANALYSIS.md) for technical details
3. Understand the [Integration Comparison](docs/INTEGRATION_COMPARISON.md) for architectural decisions
4. Read the [Testing Guide](docs/TESTING_GUIDE.md) for validation strategies

---

**Made with ❤️ for radiology teams**
