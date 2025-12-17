# Prep Page Analysis & Improvement Plan

## Executive Summary

Analysis of the prep page (`templates/prep_next_day.html`) reveals several issues and opportunities for improvement. This document details findings and proposes solutions.

---

## 1. SAME DAY vs NEXT DAY EDIT DISCREPANCIES

### Current Implementation
- **Change Today** tab: Uses `/api/live-schedule/*` endpoints
- **Prep Tomorrow** tab: Uses `/api/prep-next-day/*` endpoints
- Both tabs use IDENTICAL rendering code (`renderTable()`)

### Identified Issues
| Issue | Location | Impact |
|-------|----------|--------|
| Only modal border color differs (green vs yellow) | Line 1516 | Subtle, easy to miss |
| No visual distinction in table rows | `renderTable()` | Users can't easily see which tab they're editing |
| Tab banner color differs but table doesn't | Lines 27-35 CSS | Inconsistent UX |

### Recommendation
Add subtle background tint to entire table area based on tab:
- **Today**: Faint green background (`#f0fff0`)
- **Tomorrow**: Faint yellow background (`#fffef0`)

---

## 2. TABLE STYLING - SLIMMING DOWN

### Current Problems

#### A. Boxes Around Every Value
```css
/* Line 57-69 */
.grid-badge { border-radius: 4px; border: 1px solid #ddd; }
.skill-val { border-radius: 3px; border: 1px solid #ddd; }
```
- Each skill value has a visible box/badge
- Creates visual clutter with many columns
- Makes the table feel "heavy"

#### B. Missing CSS Classes
Lines 225-228 and 302-305 use classes without CSS definitions:
```html
<span class="skill-val skill-val-1">1</span>  <!-- No CSS! -->
<span class="skill-val skill-val-0">0</span>  <!-- No CSS! -->
<span class="skill-val skill-val--1">-1</span> <!-- No CSS! -->
```

### Recommendation - Cleaner Table Design
1. **Remove box borders** - Use background color only (more subtle)
2. **Reduce padding** - Make cells more compact
3. **Use color bands** - Skill values indicated by text/background color, not borders
4. **Add column background colors** - Faint modality colors behind skill columns

---

## 3. BACKGROUND COLORATION (Modality Colors as Columns)

### Available Colors (from config.yaml)
| Modality | Nav Color | Background Color |
|----------|-----------|-----------------|
| CT | #1a5276 | #e6f2fa (light blue) |
| MR | #777777 | #f9f9f9 (light gray) |
| X-ray | #239b56 | #e0f2e9 (light green) |
| Mammo | #e91e63 | #fce4ec (light pink) |

### Current State
- `background_color` is defined in config but **NOT USED** in table cells
- Only `nav_color` is used in header

### Implementation Plan
Apply faint background color to all cells in a modality's columns:
```javascript
// In renderCell() function
const modSettings = MODALITY_SETTINGS[modKey] || {};
const bgColor = modSettings.background_color || '#f8f9fa';
return `<td class="${cellClass}" style="background:${bgColor};">...</td>`;
```

This creates visual "lanes" for each modality, making the grid easier to scan.

---

## 4. WEIGHT ENTRIES - CONSOLIDATION

### Current Problem (Lines 1359-1377, 1175-1181)
```
| Worker | Shift | ... | CT Skills... | MR Skills... | Mod.CT | Mod.MR | Mod.XR | Mod.MA |
```
- **4 modifier columns** (one per modality)
- Modifier should be **ONE per worker per shift**, not per modality
- Comment at line 2195: "Modifier controls the actual weight calculation"

### The Confusion
- Each modality entry stores its own `modifier` value
- But conceptually, modifier is a **worker workload factor** for the entire shift
- A worker with modifier=0.5 works at half capacity **across all their modalities**

### Current Data Flow
```javascript
// Line 1069-1072 in buildEntriesByWorker()
grouped[workerName].shifts[shiftKey].modalities[modKey] = {
  skills: entry.skills,
  row_index: entry.row_index,
  modifier: entry.modifier  // STORED PER MODALITY
};
```

### Recommended Change
**Option A: Single Modifier Column** (Preferred)
- One "Modifier" column per row (worker-shift)
- Applies to all modalities for that shift
- Saves 3 columns width

**Option B: Visual Consolidation**
- Keep per-modality storage but only DISPLAY once
- First non-placeholder modality's modifier shown
- Others hidden

### Implementation
```javascript
// In renderTable(), after skill columns:
// Single modifier cell for the row (not per modality)
const firstMod = modKeysToShow.find(m => shift.modalities[m]?.row_index >= 0);
const modVal = shift.modalities[firstMod]?.modifier || 1.0;
tr.innerHTML += `<td class="grid-modifier"><span class="modifier-badge">${modVal.toFixed(2)}x</span></td>`;
```

---

## 5. SHIFTS/ROLES vs TASKS/GAPS - CRITICAL ISSUES

### A. Inconsistent Gap Detection (BUG)

**Backend (app.py:1158)** - Uses config:
```python
if rule.get('exclusion', False):
    # This is a gap/exclusion
```

**Frontend (prep_next_day.html:1020)** - Uses STRING MATCHING:
```javascript
const isGapRow = taskLower.includes('board') || taskLower.includes('gap');
```

**PROBLEM**: A gap named "Besprechung" (meeting) or "Fortbildung" (training) from config:
```yaml
- match: "Besprechung"
  type: "gap"
  exclusion: true
```
...would NOT trigger `isGapRow` because it doesn't contain "board" or "gap"!

### B. Missing Tags on CSV Load

When CSV is loaded:
1. Backend processes rules and identifies type (shift vs gap)
2. Task name is stored in `tasks` field
3. **BUT the `type` field is NOT passed to frontend!**

**app.py:3351-3354** sends to template:
```python
task_role = {
    'name': rule.get('match', ''),
    'type': rule_type,  # "shift" or "gap"
    'exclusion': rule.get('exclusion', False),
    ...
}
```

**BUT** the DataFrame rows don't carry the `type` - they only have `tasks` (the matched name).

### C. Gap Behavior Not Fully Implemented

When a gap is selected in edit modal:
- The dropdown has `data-type="gap"` and `data-exclusion="true"` attributes
- But the save logic doesn't use these to set all skills to -1
- User manually sees "Tasks / Gaps (makes -1)" but it doesn't auto-apply

### Recommended Fixes

#### Fix 1: Proper Gap Detection
```javascript
// Replace line 1020
function isGapTask(taskName) {
  const gapTasks = getGapTasks();  // Already exists - uses config
  return gapTasks.some(g => g.name.toLowerCase() === (taskName || '').toLowerCase());
}

const isGapRow = isGapTask(taskStr);
```

#### Fix 2: Store Type in Data
When loading CSV, include `type` in row data:
```python
# In build_working_hours_from_medweb()
entry['task_type'] = rule.get('type', 'shift')
entry['is_exclusion'] = rule.get('exclusion', False)
```

#### Fix 3: Auto-Apply Gap Skills
When task dropdown changes to gap type:
```javascript
taskSelect.addEventListener('change', (e) => {
  const selectedOption = e.target.selectedOptions[0];
  const isGap = selectedOption.dataset.type === 'gap' || selectedOption.dataset.exclusion === 'true';
  if (isGap) {
    // Set all skill inputs to -1
    modalEl.querySelectorAll('.skill-input').forEach(inp => inp.value = -1);
  }
});
```

---

## 6. PROPOSED UI CHANGES SUMMARY

### Before (Current)
```
| Worker | Shift | Task | [CT: Not Pri Gyn...] | [MR: Not Pri Gyn...] | [XR: Not Pri Gyn...] | [MA: Not Pri Gyn...] | Mod.CT | Mod.MR | Mod.XR | Mod.MA | Actions |
```
- 4 modalities × 9 skills = 36 skill columns
- 4 modifier columns
- Each cell has a bordered badge

### After (Proposed)
```
| Worker | Shift | Task | [CT: Not Pri Gyn...] | [MR: Not Pri Gyn...] | [XR: Not Pri Gyn...] | [MA: Not Pri Gyn...] | Mod. | Actions |
```
- Same 36 skill columns but with:
  - Faint modality background colors (visual lanes)
  - No borders on values (cleaner)
  - Compact styling
- **Single modifier column** (saves 3 columns)
- Tab-specific background tint for today/tomorrow

---

## 7. IMPLEMENTATION PRIORITY

| Priority | Task | Effort | Impact |
|----------|------|--------|--------|
| P0 | Fix gap detection (use config, not string matching) | Low | High (correctness) |
| P1 | Consolidate modifier to single column | Medium | High (space saving) |
| P2 | Add modality background colors to columns | Low | Medium (UX) |
| P3 | Remove box borders, use cleaner styling | Low | Medium (visual) |
| P4 | Add tab-specific table background | Low | Low (clarity) |
| P5 | Add missing CSS classes for skill values | Low | Low (consistency) |

---

## 8. CODE CHANGES REQUIRED

### Files to Modify
1. `templates/prep_next_day.html`
   - `renderTable()` - modifier consolidation, background colors
   - `buildEntriesByWorker()` - gap detection fix
   - `renderTableHeader()` - remove extra modifier columns
   - CSS section - add missing classes, cleaner styling

2. `app.py` (optional but recommended)
   - Include `task_type` in row data for explicit gap identification

### Estimated Lines Changed
- ~100-150 lines in prep_next_day.html
- ~10-20 lines in app.py (if including type in data)

---

## 9. DECISION POINTS FOR USER

Before implementation, please confirm:

1. **Modifier Column**: Single column (recommended) or keep per-modality display?
2. **Gap Handling**:
   - Fix detection only?
   - Or also auto-set skills to -1 when gap selected?
3. **Styling**:
   - Completely remove borders?
   - Or keep subtle borders with background colors?
4. **Tab Distinction**: Add background tint to table area?

---

## 10. ALTERNATIVE APPROACH - Rethink Gaps Entirely

The current gap system tries to do two things:
1. **Exclusions** (during CSV import) - punches out time from shifts
2. **Gap rows in UI** - shows -1 everywhere

These are conceptually different:
- **Exclusion**: "Worker is unavailable 15:00-17:00 due to Board"
- **Gap row**: "This entire entry is a gap, all skills = -1"

### Consider: Separate Concerns
- **Exclusions**: Handle ONLY during CSV import (as currently done)
- **UI**: Don't show gap rows at all - they're not "work assignments"
- **Visual**: Show gaps as time annotations on shift rows, not separate entries

This would require a larger refactor but would make the model cleaner.

---

*Analysis completed. Ready for implementation pending user decisions.*
