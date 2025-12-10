# RadIMO Medweb CSV Workflow (v19)

Human-readable guide to how medweb CSV files move through RadIMO v19, including where configuration is applied and how shifts are interpreted. All timings, exclusions, and preload behaviour in this version reflect the current `config.yaml` defaults.

---

## 📋 Overview

- Single CSV upload populates all modalities (CT, MR, X-ray) with consistent parsing.
- Configurable mapping rules attach modality, shift, and base skills to each activity description.
- Shift times, Friday exceptions, and exclusion windows are defined in the configuration and applied automatically.
- Worker-specific skill overrides refine the defaults without altering the CSV.
- Shifts are normalized so overnight windows (for example 22:00–06:00) keep workers available across midnight and report correct durations.
- Automatic preload runs daily at **07:30 CET** using the stored master CSV; manual uploads and emergency refreshes stay available.
- Next-day editing happens in a dedicated interface so today’s assignments remain stable.

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

## 📤 Upload Strategies

### 1. Manual Upload (On-Demand)

**Use Case:** Upload schedule for a specific date immediately.

**Steps:**
1. Open the admin panel at `/upload`.
2. Use **📤 Medweb CSV Upload**.
3. Pick the CSV and target date (today, tomorrow, or any future date).
4. Upload to process immediately.

**What Happens:**
- The CSV is parsed for the selected date with mapping rules and roster overrides.
- Shift times come from the config; overnight ranges are rolled into the next calendar day so availability and durations stay accurate.
- Working tables for each modality are rebuilt and counters reset for a clean slate.
- The file is saved as the master copy for future preloads.

**When to Use:** initial setup, mid-day updates, alternate target dates, or config testing.

---

### 2. Auto-Preload (Scheduled Daily)

**Use Case:** Automatically load the next workday schedule every morning.

**Schedule:** **07:30 CET** daily.

**Next Workday Logic:** Monday–Thursday → next day; Friday → Monday. Holidays still require manual intervention.

**What Happens:**
- Scheduler reads the master CSV and selects the next workday.
- Parsing, normalization, exclusions, and roster overrides run as in manual upload.
- Working tables and counters are refreshed for a new day; results are logged.

**Requirements:** the master CSV exists and includes the target date; the application is running at 07:30 CET.

**If Auto-Preload Fails:**
- Check `selection.log` for the timestamped preload entry.
- Verify the master CSV exists and covers the next workday.
- Manually upload via the admin panel as a fallback.

---

### 3. Preload Next Workday (Manual Trigger)

**Use Case:** Manually preload the next workday ahead of time.

**Steps:**
1. Open the admin panel at `/upload`.
2. Use **🔮 Preload Nächster Arbeitstag**.
3. Choose the CSV file to use.
4. Confirm the shown target date (e.g., Monday if triggered on Friday).
5. Start the preload.

**What Happens:**
- Runs the same parsing and normalization pipeline as the scheduled preload.
- Useful for testing next-workday logic or preparing outside the 07:30 run.
- Updates the master CSV so the next scheduled preload uses the latest file.

---

### 4. Force Refresh (Full Reset)

**Use Case:** Complete same-day schedule rebuild when assignments must be discarded.

**⚠️ WARNING:** This deletes all assignment history and counters for today. Use only when a full rebuild is necessary.

**Steps:**
1. Open the admin panel at `/upload`.
2. Use **🔄 Force Refresh Today**.
3. Choose the CSV file.
4. Confirm the warning and reload.

**What Happens:**
- All counters and assignment history for today are reset.
- The new schedule is parsed with the same normalization rules used elsewhere.
- The day restarts from a clean state; previous assignments are not preserved.

**When to Use:** Only for major schedule rebuilds that require resetting all assignment history.

---

## 📝 Schedule Editing

The Schedule Edit page (`/prep-next-day`) lets admins prepare schedules and make adjustments. It is ideal for correcting mapping edge cases, adjusting times (including overnight spans), or refining skills.

**Access:** Admin Panel → **📝 Nächsten Tag Bearbeiten**

### Two Editing Modes

#### Simple Mode

**For:** Quick edits and corrections.

**Features:** inline cell editing for names, times, skills, and modifiers; edited cells are highlighted until saved.

**Editable Fields:**
- Worker name/abbreviation.
- Start and end times (HH:MM), with overnight spans allowed.
- Skill flags (-1 excluded, 0 fallback, 1 active).
- Individual workload modifier.

**Skill Value Colors:** 🟢 1 active; 🟡 0 fallback; 🔴 -1 excluded.

---

#### Advanced Mode

**For:** Structural changes, adding or removing workers, and bulk skill updates.

**Features:**
- Add worker rows with default values that can be adjusted immediately.
- Delete worker rows with confirmation prompts.
- Bulk-set a skill value across the current modality.
- All Simple Mode features remain available.

---

## ⚙️ Configuration Notes

- **Mapping rules** define which activity text maps to which modality and shift name; first match wins.
- **Shift times** live in the configuration with optional Friday overrides. Overnight ranges are supported and are automatically rolled into the next day when needed.
- **Time exclusions** split shifts into available segments while keeping total coverage accounting accurate.
- **Worker skill overrides** apply after parsing, first modality-specific, then global defaults.

---

## ✅ Quick Checklist

- Upload or update the master medweb CSV whenever schedule data changes.
- Confirm mapping rules and shift definitions reflect current medweb activity names and times, including any overnight coverage.
- Use Day Control for same-day adjustments; use next-day prep for planned changes; use force refresh only for complete schedule rebuilds.
- Monitor `selection.log` after preloads to verify the correct date, modality counts, and worker totals.
