# SBZDashboard Integration Plan

**Planning Document: Integrating SBZDashboard schedule generator with RadIMO SBZ worker assignment system**

---

## 📋 Current State Analysis

### **RadIMO SBZ** (Worker Assignment System)
- **Purpose**: Real-time worker assignment with load balancing
- **Input**: 3 separate Excel files (SBZ_ct.xlsx, SBZ_mr.xlsx, SBZ_xray.xlsx)
- **Excel Format**:
  - Tabelle1: PPL, Modifier, VON, BIS, [Skill Columns with -1/0/1]
  - Tabelle2: Info texts
- **Modalities**: ct, mr, xray
- **Skills**: Normal, Notfall, Privat, Herz, Msk, Chest
- **Workflow**: Manual upload → Parse → Assign workers → Track load

### **SBZDashboard** (Schedule Generator)
- **Purpose**: Convert monthly CSV from medweb into daily Excel schedules
- **Input**: Single CSV (medweb.csv) with all modalities
- **Output**: 3 separate Excel files (CTSBZ_YYYYMMDD.xlsx, MRSBZ_YYYYMMDD.xlsx, ChirSBZ_YYYYMMDD.xlsx)
- **Excel Format**:
  - Tabelle1: PPL, Modifier, TIME (with semicolons), Normal, Notfall, Herz, PP, Msk, Chest (binary 0/1)
  - Tabelle2: Info texts
- **Modalities**: CT, MRT, Chir, FA/Fellow
- **Complex Logic**:
  - Shift time calculation (Friday vs Mon-Thu, special roles, labels)
  - Role detection (OA, PP, FA/Fellow, Chir Assistent)
  - Besonderheiten (special circumstances like "Aufklärung", "Cardiac", boards)
  - Personalnummer-based overrides
- **Config Files**: config.yml, shifts.yml

---

## 🔍 Key Differences & Challenges

### 1. **Modality Naming**
| Dashboard | RadIMO | Notes |
|-----------|--------|-------|
| CT | ct | Same concept, different case |
| MRT | mr | Dashboard uses "MRT", RadIMO uses "mr" |
| Chir | (none) | Chirurgie not in RadIMO currently |
| XRAY | xray | Not in Dashboard |
| FA/Fellow | (none) | Special role that gets added to CT/MRT |

### 2. **Skill Values**
| Dashboard | RadIMO | Meaning |
|-----------|--------|---------|
| 0 | -1 | Excluded |
| 1 | 0 or 1 | Active (Dashboard doesn't distinguish passive) |
| (none) | 0 | Passive (only fallback) - NEW in RadIMO |

### 3. **Excel Format**
| Aspect | Dashboard | RadIMO |
|--------|-----------|--------|
| Time Format | Single TIME column with semicolons (07:30-11:30; 13:30-15:00) | VON/BIS columns (07:00, 13:00) |
| Multiple Shifts | Semicolon-separated in one row, gets exploded | One row per shift (needs multiple rows) |
| Skill Columns | Binary (0/1) for Normal, Notfall, Herz, PP, Msk, Chest | Ternary (-1/0/1) for all skills |

### 4. **Workflow Differences**
| Aspect | Dashboard | RadIMO |
|--------|-----------|--------|
| Source | Monthly CSV from medweb | Manual Excel files |
| Frequency | Generate daily schedules | Upload as needed |
| Editing | No manual editing in Dashboard | Manual editing expected per modality |
| Output | Automated generation | Manual upload |

---

## 🎯 Integration Goals

1. **Unified Upload**: Single upload point instead of 3 separate files
2. **Config-Driven Skills**: Support different skill sets per site/department
3. **Preserve Dashboard Logic**: Keep German radiology-specific business rules
4. **Backward Compatible**: Existing 3-file upload should still work
5. **Reduce Manual Work**: Eliminate repetitive manual Excel creation

---

## 📐 Architecture Options

### **Option 1: Merge into Single Application** ⭐ RECOMMENDED

**Architecture:**
```
RadIMO SBZ (Extended)
├── /                      # Main assignment interface (existing)
├── /by-skill             # Skill-based view (existing)
├── /upload               # Admin panel (existing)
├── /schedule-generator    # NEW: Dashboard functionality
│   ├── Upload medweb.csv
│   ├── Configure date
│   ├── Preview generated schedules
│   └── Generate & import to RadIMO
├── /timetable            # Timeline (existing)
└── /login                # Auth (existing)
```

**Benefits:**
- ✅ Single codebase, unified auth
- ✅ Direct data flow (no file export/import)
- ✅ Shared configuration (config.yaml)
- ✅ One deployment, one URL
- ✅ Can preview before applying to RadIMO

**Challenges:**
- ⚠️ More complex codebase
- ⚠️ Dashboard logic is specific to one site (might not apply to all RadIMO users)
- ⚠️ Coupling two different concerns

**Implementation:**
- Add Dashboard's `build_final_df()` and `generate_ctsbz_excel()` as new modules
- Create `/schedule-generator` route with simplified UI
- Add "Import from Schedule Generator" button in `/upload`
- Keep shifts.yml separate or merge into config.yaml

---

### **Option 2: Keep Separate with API Integration**

**Architecture:**
```
SBZDashboard (Standalone)          RadIMO SBZ (Existing)
├── / (medweb upload)              ├── / (assignment)
├── Generate Excel                 ├── /by-skill
└── POST to RadIMO API ────────────> /api/import-schedule
                                   ├── /upload (manual)
                                   └── /timetable
```

**Benefits:**
- ✅ Clean separation of concerns
- ✅ Dashboard can be used independently
- ✅ Different update cycles
- ✅ Easier to maintain separately

**Challenges:**
- ⚠️ Two applications to deploy
- ⚠️ API design and auth complexity
- ⚠️ File-based integration (less direct)
- ⚠️ Two configs to maintain

**Implementation:**
- Add `/api/import-schedule` endpoint to RadIMO
- Dashboard POSTs Excel files or JSON
- RadIMO validates and imports
- Add API key authentication

---

### **Option 3: Dashboard as RadIMO Plugin/Module**

**Architecture:**
```
RadIMO SBZ
├── Core (existing assignment logic)
├── Plugins/
│   └── SBZDashboard/
│       ├── __init__.py
│       ├── schedule_generator.py
│       ├── shifts.yml
│       └── templates/
└── config.yaml (extended with dashboard settings)
```

**Benefits:**
- ✅ Modular architecture
- ✅ Optional feature (sites that don't need it can disable)
- ✅ Shared config but isolated code
- ✅ Can be enabled/disabled via config

**Challenges:**
- ⚠️ Requires plugin architecture design
- ⚠️ More initial setup work
- ⚠️ Config becomes more complex

---

## 🎨 Unified Upload Design

### **Approach A: Single Excel with Modality Column**

**Format:**
```
PPL              | Modifier | VON   | BIS   | Modalität | Normal | Notfall | Herz | ...
Dr. Müller (AM)  | 1.0      | 07:30 | 15:00 | ct        | 1      | 1       | 0    | ...
Dr. Schmidt (BS) | 1.0      | 07:30 | 15:45 | mr        | 1      | 1       | 1    | ...
Dr. Braun (CB)   | 1.0      | 07:30 | 16:30 | chir      | 1      | 1       | 0    | ...
```

**Pros:**
- ✅ Simple flat structure
- ✅ Easy to parse
- ✅ CSV-compatible
- ✅ Can add/remove modalities dynamically

**Cons:**
- ❌ Loses sheet-based organization
- ❌ Harder to manually edit (all modalities mixed)
- ❌ Tabelle2 (info texts) would need modality prefix

---

### **Approach B: Single Excel with Multiple Sheets** ⭐ RECOMMENDED

**Format:**
```
Workbook: SBZ_unified_20250120.xlsx
├── Sheet: ct
│   ├── PPL, Modifier, VON, BIS, Normal, Notfall, Herz, PP, Msk, Chest
│   └── (CT workers only)
├── Sheet: mr
│   ├── PPL, Modifier, VON, BIS, Normal, Notfall, Herz, PP, Msk, Chest
│   └── (MR workers only)
├── Sheet: xray
│   ├── PPL, Modifier, VON, BIS, Normal, Notfall, Herz, PP, Msk, Chest
│   └── (XRAY workers only)
├── Sheet: chir (NEW)
│   ├── PPL, Modifier, VON, BIS, Normal, Notfall, Herz, PP, Msk, Chest
│   └── (Chir workers only)
└── Sheet: info
    ├── Modality (column: ct, mr, xray, chir)
    └── Info Text
```

**Pros:**
- ✅ Organized by modality (familiar structure)
- ✅ Easy manual editing per modality
- ✅ Clear separation
- ✅ Info texts can have modality column

**Cons:**
- ❌ More complex parsing
- ❌ Needs error handling per sheet

**Implementation:**
```python
def parse_unified_roster(filepath):
    """Parse unified Excel with multiple sheets"""
    workbook = pd.ExcelFile(filepath)

    modality_data = {}
    for sheet_name in workbook.sheet_names:
        if sheet_name == 'info':
            # Parse info texts
            info_df = pd.read_excel(workbook, sheet_name)
            continue

        # Parse modality sheet (ct, mr, xray, chir)
        modality_data[sheet_name] = pd.read_excel(workbook, sheet_name)

    return modality_data
```

---

### **Approach C: Hybrid (Unified + Per-Modality Overrides)**

**Workflow:**
1. Upload unified file → Populates all modalities
2. Optional: Upload individual modality files → Overrides specific modality
3. RadIMO uses unified by default, falls back to individual files

**Pros:**
- ✅ Best of both worlds
- ✅ Gradual migration path
- ✅ Handles sites with partial adoption

**Cons:**
- ❌ Most complex implementation
- ❌ Potential confusion (which file is active?)
- ❌ Harder to maintain

---

## ⚙️ Config-Driven Skill Presets

### **Problem:**
- Different sites might use different skill sets
- Example: Site A uses [Normal, Notfall, Herz], Site B uses [Normal, Notfall, Privat, Msk]
- Dashboard uses hardcoded [Normal, Notfall, Herz, PP, Msk, Chest]

### **Solution: Skill Preset System**

**config.yaml Extension:**
```yaml
# Existing config stays
modalities:
  ct:
    label: CT
    factor: 1.0
  mr:
    label: MR
    factor: 1.2
  chir:  # NEW modality
    label: Chirurgie
    factor: 1.0

# NEW: Skill presets and mappings
skill_presets:
  default:
    - Normal
    - Notfall
    - Privat
    - Herz
    - Msk
    - Chest

  freiburg:  # Dashboard's current setup
    - Normal
    - Notfall
    - Herz
    - PP
    - Msk
    - Chest

  simple:  # Minimal setup
    - Normal
    - Notfall

# Active preset
active_skill_preset: default  # or 'freiburg', 'simple'

# Skill name mappings (for import from external systems)
skill_mappings:
  Emergency: Notfall      # Map "Emergency" → "Notfall"
  Heart: Herz             # Map "Heart" → "Herz"
  Private: Privat         # Map "Private" → "Privat"
  Regular: Normal         # Map "Regular" → "Normal"
  PP: Privat              # Map "PP" → "Privat" (or keep as separate skill)

# Dashboard-specific config (if merged)
dashboard:
  enabled: true
  besonderheiten:
    - {keyword: "Aufklärung", label: "Aufklärung"}
    - {keyword: "Cardiac", label: "Cardiac"}
  shifts_config_file: shifts.yml
  personalnummern_override:
    "Dorina Korbmacher": "KORB"
  skill_overrides:
    "NUK": 0
  modifier_overrides:
    "KRUE": "1"
```

**Benefits:**
- ✅ Flexible for different sites
- ✅ Easy to add new presets
- ✅ Import/export mappings
- ✅ Dashboard-specific config isolated

---

## 🔄 Data Flow Options

### **Flow 1: Dashboard → Unified File → RadIMO (Recommended for Merge)**

```
medweb.csv
    ↓
Dashboard Logic
(build_final_df, shift calculation)
    ↓
Generate Unified Excel (multi-sheet)
SBZ_unified_20250120.xlsx
├── ct (sheet)
├── mr (sheet)
├── chir (sheet)
└── info (sheet)
    ↓
RadIMO Upload
(parse_unified_roster)
    ↓
Load into modality_data
    ↓
Worker Assignment System
```

**Advantages:**
- ✅ Direct integration
- ✅ No intermediate files
- ✅ Preview before applying

---

### **Flow 2: Dashboard → Individual Files → RadIMO (Current, Keep for Compatibility)**

```
medweb.csv
    ↓
Dashboard Logic
    ↓
Generate 3 Excel files
├── CTSBZ_20250120.xlsx
├── MRSBZ_20250120.xlsx
└── ChirSBZ_20250120.xlsx
    ↓
Manual Upload (3 times)
    ↓
RadIMO (existing logic)
```

**Advantages:**
- ✅ Backward compatible
- ✅ No code changes
- ✅ Works with existing workflow

---

### **Flow 3: API-Based (Recommended for Separate Apps)**

```
medweb.csv
    ↓
Dashboard (standalone)
    ↓
POST /api/import-schedule
{
  "date": "2025-01-20",
  "modalities": {
    "ct": [{workers...}],
    "mr": [{workers...}],
    "chir": [{workers...}]
  }
}
    ↓
RadIMO API Endpoint
    ↓
Validate & Import
    ↓
Worker Assignment System
```

**Advantages:**
- ✅ Clean separation
- ✅ RESTful design
- ✅ Can be called by other systems
- ✅ JSON format (easier validation)

---

## 📝 Recommended Approach

### **Phase 1: Merge Dashboard as Module** (Weeks 1-2)

**Why:**
- Most value for Freiburg site (immediate benefit)
- Unified workflow
- Can evolve into plugin later if needed

**Implementation:**

1. **Create schedule_generator module** (app.py)
   ```python
   # schedule_generator.py
   def build_schedule_from_csv(csv_path, selected_date):
       """Dashboard's build_final_df logic"""
       pass

   def generate_unified_excel(df, output_path):
       """Create multi-sheet Excel"""
       pass

   def import_unified_to_radimo(excel_path):
       """Parse and load into modality_data"""
       pass
   ```

2. **Add /schedule-generator route**
   ```python
   @app.route('/schedule-generator')
   @admin_required
   def schedule_generator():
       return render_template('schedule_generator.html')

   @app.route('/api/generate-schedule', methods=['POST'])
   @admin_required
   def generate_schedule_api():
       csv_file = request.files['csv']
       date = request.form['date']

       # Generate schedule
       df = build_schedule_from_csv(csv_file, date)

       # Return preview JSON
       return jsonify(df.to_dict('records'))

   @app.route('/api/apply-schedule', methods=['POST'])
   @admin_required
   def apply_schedule():
       # Import into modality_data
       import_unified_to_radimo(...)
       return jsonify({'success': True})
   ```

3. **Create schedule_generator.html template**
   - Upload medweb.csv
   - Select date
   - Preview generated schedule
   - "Apply to RadIMO" button

4. **Update config.yaml**
   - Add dashboard section
   - Add chir modality
   - Add skill presets
   - Keep shifts.yml separate (or inline it)

---

### **Phase 2: Unified Upload Format** (Weeks 3-4)

1. **Extend parse_roster() to handle multi-sheet**
   ```python
   def parse_roster(filepath):
       if is_unified_format(filepath):
           return parse_unified_roster(filepath)
       else:
           return parse_single_modality(filepath)  # Existing logic
   ```

2. **Update /upload UI**
   - Add "Unified Upload" tab
   - Keep "Per-Modality Upload" tab (backward compatible)
   - Show which format is active

3. **Add format converter**
   - Convert 3 separate files → unified
   - Convert unified → 3 separate (for export)

---

### **Phase 3: Config-Driven Skills** (Weeks 5-6)

1. **Implement skill preset system**
   ```python
   def load_active_skills():
       preset_name = APP_CONFIG['active_skill_preset']
       return APP_CONFIG['skill_presets'][preset_name]

   def map_skill_name(external_name):
       mappings = APP_CONFIG['skill_mappings']
       return mappings.get(external_name, external_name)
   ```

2. **Update UI to be dynamic**
   - Generate skill columns from active preset
   - Admin panel shows active preset
   - Can switch presets (requires data migration)

3. **Add skill migration tool**
   - Convert data when switching presets
   - Handle missing skills (set to default values)

---

### **Phase 4: Plugin Architecture** (Optional, Weeks 7-8)

1. **Create plugin system**
   ```python
   # plugins/__init__.py
   class Plugin:
       def init_app(self, app):
           pass

       def register_routes(self, app):
           pass

   # plugins/schedule_generator/__init__.py
   class ScheduleGeneratorPlugin(Plugin):
       def register_routes(self, app):
           from . import routes
           routes.register(app)
   ```

2. **Config-driven plugin loading**
   ```yaml
   plugins:
     schedule_generator:
       enabled: true
       config_file: shifts.yml
   ```

---

## 🚀 Implementation Estimates

| Phase | Tasks | Effort | Priority |
|-------|-------|--------|----------|
| **Phase 1: Merge Dashboard** | Module creation, route setup, basic UI | 16-20h | HIGH |
| **Phase 2: Unified Upload** | Multi-sheet parsing, UI updates | 10-12h | MEDIUM |
| **Phase 3: Config Skills** | Preset system, skill mappings | 12-15h | MEDIUM |
| **Phase 4: Plugin Arch** | Plugin system, isolation | 15-20h | LOW |
| **Testing & Docs** | Integration tests, user guide | 8-10h | HIGH |
| **Total** | | **61-77h** | |

**MVP (Phase 1 + 2):** ~30 hours → 4-5 days of development

---

## ⚠️ Migration Strategy

### **Backward Compatibility Plan:**

1. **Keep existing 3-file upload working**
   - Don't break current users
   - Add unified as optional feature
   - Gradual migration

2. **Data format detection**
   ```python
   if 'Modalität' in df.columns:
       # Unified format
   elif excel.sheet_names contains ['ct', 'mr', 'xray']:
       # Multi-sheet format
   else:
       # Single modality format (existing)
   ```

3. **Config versioning**
   ```yaml
   version: 2.0  # Add version to config
   # Old configs default to v1.0 behavior
   ```

4. **Feature flags**
   ```yaml
   features:
     unified_upload: true
     schedule_generator: true
     skill_presets: false  # Rollout gradually
   ```

---

## 🎯 Decision Matrix

| Criterion | Option 1: Merge | Option 2: Separate | Option 3: Plugin |
|-----------|----------------|-------------------|------------------|
| **Development Effort** | Medium (20h) | High (30h) | Very High (35h) |
| **Maintenance** | Medium | High (2 apps) | Medium |
| **User Experience** | Best (single app) | Good | Best |
| **Flexibility** | Medium | High | Highest |
| **Deployment** | Easy | Complex | Medium |
| **For Freiburg Site** | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐⭐ |
| **For Generic Use** | ⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ |

**Recommendation:** **Option 1 (Merge)** for Phase 1, evolve to **Option 3 (Plugin)** later if needed.

---

## 📚 Next Steps

1. ✅ Review this plan with stakeholders
2. ✅ Decide on Option 1 vs 2 vs 3
3. ✅ Confirm multi-sheet format for unified upload
4. ✅ Prototype schedule_generator module (2 days)
5. ✅ Test with real medweb.csv data
6. ✅ Implement Phase 1 (MVP)
7. ✅ Deploy and gather feedback
8. ✅ Plan Phase 2 based on usage

---

## 🤔 Open Questions

1. **Chir modality in RadIMO?**
   - Should RadIMO add 'chir' as a fourth modality?
   - Or map chir → xray in config?

2. **FA/Fellow role handling?**
   - Dashboard adds FA/Fellow to both CT and MRT
   - Should RadIMO have a separate "role" concept vs modality?

3. **Skill value mapping?**
   - Dashboard uses binary (0/1), RadIMO uses ternary (-1/0/1)
   - Should Dashboard adopt ternary? Or map during import?

4. **Info texts per modality?**
   - Currently Tabelle2 is per-file
   - Unified format needs modality column in info sheet

5. **Time format standardization?**
   - Dashboard uses semicolon-separated (07:30-11:30; 13:30-15:00)
   - RadIMO uses VON/BIS columns
   - Need converter function?

---

**Document Version:** 1.0
**Date:** 2025-01-20
**Status:** Planning / Awaiting Decision
