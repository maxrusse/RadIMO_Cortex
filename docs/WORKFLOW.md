- Single **Master CSV** upload populates current and future workday schedules.
- Configurable mapping rules attach modality, shift, and base skills to activity descriptions.
- Overnight shift handling (e.g., 22:00–06:00) is automated at the parsing stage.
- **GAP Handling**: meetings and boards trigger split shifts, ensuring coverage accounts for unavailability.
- **Skill Management**: workers pull global skill levels from the Skill Matrix (saves directly).
- **Daily Prep**: admins use the "Prep Tomorrow" mode to adjust the next day's rotation before it goes live at the **configured reset time** (default 07:30 CET).

---

## 🔄 Complete Flow

1) **Source**: medweb exports a monthly CSV with worker activities.
2) **Ingestion**: the CSV is uploaded once as the master copy; it powers both manual processing and the daily preload.
3) **Parsing**: mapping rules attach modality and shift names; shift times are derived from the config with Friday-specific exceptions when defined.
4) **Normalization**: shift windows are normalized into start/end datetimes, rolling end times into the next day when needed, so overnight coverage is retained. Durations always reflect the full window.
5) **Exclusions**: scheduled boards or meetings split shifts into available segments without losing total coverage accounting.
6) **Rosters**: worker skill overrides apply after parsing to adjust base skills per modality or globally.
7) **Preparation**: optional edits for the next workday occur on `/prep-next-day`, keeping current-day assignments untouched.
8) **Assignment**: real-time selection uses the normalized shifts and skill values to balance workload and honour fallback rules.

---

## 📤 Master CSV Strategy

RadIMO uses a single monthly CSV (`master_medweb.csv`) to power the entire schedule.

### 1. Upload Master
**Action**: Admin Panel -> **Master CSV Upload**
- Saves the file to `uploads/master_medweb.csv`.
- This file acts as the source of truth for "Load Today" and "Preload Tomorrow".

### 2. Daily Operations
**Action**: Admin Panel -> **Load Today**
- Manually trigger a rebuild of today's schedule from the Master CSV.
- **WARNING**: This resets all current assignment counters and history.

### 3. Future Planning
**Action**: Admin Panel -> **Preload Tomorrow**
- Fetches the next workday's data from the Master CSV.
- Populates the "Prep Tomorrow" view in Schedule Edit.

### 4. Automated Reset
- Every morning at the **configured time** (default 07:30 CET), the system automatically performs a "Load Today" logic for the new date.

---

## 📝 Schedule Editing (`/prep-next-day`)

Admins can adjust "Today" (Live) or plan "Tomorrow" (Staged).

**Features:**
- **Manual Highlighting**: Any shifts added or edited manually by an admin are highlighted (subtle yellow) to distinguish them from auto-loaded Master CSV data.
- **Split Shift (GAP)**: Add a meeting (e.g., "Board 15:00-16:00") and the system automatically splits the worker's shift into two active segments.
- **Linked Gaps**: Split shifts are linked via `gap_id`. Deleting one segment removes the entire linked chain.

---

## ⚙️ Configuration Notes

- **Mapping Rules**: First match wins. Order from specific to general.
- **Overnight Shifts**: Supported (e.g., `22:00-06:00`); end time is rolled forward by 24h internally.
- **Skill Roster**: Saves directly to `worker_skill_roster.json`; priority over mapping defaults.

---

## ✅ Quick Checklist

- [ ] Upload Master CSV at start of month.
- [ ] Review "Prep Tomorrow" in the evening.
- [ ] Use "Live Edit" for same-day sickness/changes.
- [ ] Monitor `selection.log` for auto-reset confirmation at 07:30.
