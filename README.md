# RadIMO SBZ - Radiology Workload Coordinator

**Radiology: Innovation, Management & Orchestration**

Smart worker assignment system for radiology teams with automatic load balancing, flexible fallback strategies, and overlapping shift support.

---

## 🎯 What is RadIMO SBZ?

RadIMO orchestrates workload distribution for radiology teams across multiple modalities (CT, MR, XRAY) and skills (Normal, Notfall, Privat, Herz, Msk, Chest). It automatically balances assignments to ensure fair distribution while respecting worker availability and skill levels.

**Key Capabilities:**
- 📊 Real-time worker assignment with automatic load balancing
- 🔄 Smart fallback strategies for overload situations
- ⏰ Dynamic shift handling with work-hour-adjusted balancing
- 📱 Two UI modes: by modality or by skill
- 📈 Cross-modality workload tracking and overflow management
- 📁 Excel-based schedule management with automatic backup

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

- **Main Interface**: `http://localhost:5000/` - By modality view
- **Skill View**: `http://localhost:5000/by-skill` - By skill view
- **Admin Panel**: `http://localhost:5000/upload` - Upload schedules & statistics
- **Timeline**: `http://localhost:5000/timetable` - Visualize shifts

---

## ✨ Key Features

### 1. **Dual View Modes**

Choose your workflow:

- **By Modality** (default): Navigate by modality (CT/MR/XRAY) → assign by skill
- **By Skill** (new): Navigate by skill (Normal/Notfall/Herz) → assign by modality

Toggle between views with one click!

### 2. **Smart Load Balancing**

- **Work-hour-adjusted ratios**: Balances workload based on hours worked, not just assignment count
- **Overlapping shift support**: Handles early/late starters fairly
- **30% imbalance threshold**: Automatic fallback when workload becomes unfair
- **Minimum assignments**: Ensures everyone gets at least 5 assignments before overloading others

### 3. **Flexible Fallback Strategies**

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

### 4. **Skill Value System**

Fine-tune worker availability:

| Value | Name | Behavior |
|-------|------|----------|
| **1** | Active | Available for primary requests + fallback |
| **0** | Passive | Available ONLY in fallback (training, backup) |
| **-1** | Excluded | NOT available (on leave, restricted) |

### 5. **Automatic Scheduling**

- **Immediate upload**: Replace schedule instantly via admin panel
- **Scheduled upload**: Stage files for 07:30 CET daily reset
- **Automatic backup**: Every upload backed up for recovery
- **Cross-modality tracking**: Global workload statistics across all teams

---

## 📊 How It Works

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
- Worker modifier (individual multipliers from Excel)

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
    Herz: [[Notfall, Normal]]  # Parallel fallback

# Modality overflow
modality_fallbacks:
  xray: [[ct, mr]]  # XRAY can borrow from both CT and MR
  ct: [mr]          # CT can borrow from MR
  mr: []            # MR cannot borrow
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

---

## 📁 Project Structure

```
RadIMO_SBZ_DEV/
├── app.py                      # Main Flask application
├── config.yaml                 # Configuration file
├── ops_check.py               # Pre-deployment checks
├── requirements.txt           # Python dependencies
├── templates/
│   ├── index.html             # By-modality view
│   ├── index_by_skill.html    # By-skill view
│   ├── upload.html            # Admin panel
│   ├── timetable.html         # Timeline visualization
│   └── login.html             # Authentication
├── static/
│   ├── vis.js                 # Timeline library
│   └── favicon.ico
├── uploads/                   # Excel schedule files
│   ├── SBZ_ct.xlsx           # Current CT schedule
│   ├── SBZ_mr.xlsx           # Current MR schedule
│   └── SBZ_xray.xlsx         # Current XRAY schedule
└── docs/                      # Documentation
    ├── SYSTEM_ANALYSIS.md     # Complete technical analysis
    ├── FRONTEND_ARCHITECTURE.md  # UI architecture details
    └── TESTING_GUIDE.md       # Testing strategies
```

---

## 📖 Documentation

Comprehensive documentation available in the `docs/` folder:

- **[SYSTEM_ANALYSIS.md](docs/SYSTEM_ANALYSIS.md)** - Complete system analysis, fallback strategies, balancing algorithms
- **[FRONTEND_ARCHITECTURE.md](docs/FRONTEND_ARCHITECTURE.md)** - UI structure, templates, API integration
- **[TESTING_GUIDE.md](docs/TESTING_GUIDE.md)** - Testing strategies, edge cases, validation

---

## 🎨 Excel File Format

### Tabelle1 (Schedule Data)

| Column | Description | Example |
|--------|-------------|---------|
| PPL | Worker name | Dr. Anna Müller |
| Kürzel | Abbreviation | AM |
| VON | Start time | 07:00 |
| BIS | End time | 13:00 |
| Modifier | Individual weight | 1.0 |
| Normal | Skill value (1/0/-1) | 1 |
| Notfall | Skill value (1/0/-1) | 1 |
| Privat | Skill value (1/0/-1) | 0 |
| Herz | Skill value (1/0/-1) | 1 |
| Msk | Skill value (1/0/-1) | -1 |
| Chest | Skill value (1/0/-1) | 0 |

### Tabelle2 (Info Texts)

Display messages on the main interface (one message per row).

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

---

## 🔄 Recent Updates

### v17 (November 2025)
- ✨ Added skill-based navigation view (`/by-skill`)
- 🔧 Implemented work-hour-adjusted ratio balancing for overlapping shifts
- 📊 Enhanced imbalance detection to use dynamic ratios
- ✅ Implemented `run_operational_checks()` for system validation
- 📝 Fixed skill value documentation (corrected -1/0/1 system)

---

## 📄 License & Contact

**RadIMO v17** - Radiology: Innovation, Management & Orchestration

For more information, see [EULA.txt](static/EULA.txt) or contact **Dr. M. Russe**.

---

## 🤝 Contributing

This is a specialized medical workload distribution system. For questions or suggestions:

1. Review the [System Analysis](docs/SYSTEM_ANALYSIS.md) documentation
2. Check the [Testing Guide](docs/TESTING_GUIDE.md) for validation strategies
3. Understand the [Frontend Architecture](docs/FRONTEND_ARCHITECTURE.md)

---

**Made with ❤️ for radiology teams**
