# Alternative Weight Calculation -- Modality Code Multiplier

## Overview

New customer requires a simplified weight model where **all skill weights are 1** (flat), but a **4-digit code per modality** applies an additional multiplier. Codes are stored in a **separate `config_code.yaml`** file. The code is selected via a popup after a user clicks on a skill-modality combination (e.g. CT > aou).

---

## What Changes

| Aspect | Current System | New Customer Model |
|---|---|---|
| Skill weights | Per-skill (e.g. notfall=1.1, cvt=1.2) | **All skills = 1.0** |
| Modality factors | Per-modality (ct=1.0, mr=1.2, xray=0.33, mammo=0.5) | **Stays as-is** |
| Skill x Modality overrides | Explicit overrides (e.g. mr+cvt=1.8) | **Removed / not used** |
| Worker modifiers (global, w) | Per-worker in roster (inverse: divide) | **Stays as-is** |
| Modality code multiplier | Does not exist | **NEW -- per-modality code list in `config_code.yaml`** |
| `config.yaml` | Full config | **Unchanged** (only add `weight_mode` flag) |
| Balancer logic | Unchanged | Unchanged (consumes final weight) |

**Existing `config.yaml` stays fully intact. One flag is added. All code data lives in `config_code.yaml`.**

---

## Weight Formula

### Full Chain (New Customer)

```
final_weight = skill_weight            = 1.0    (always 1, from config)
             * modality_factor         = 1.1    (from config.yaml, e.g. mr=1.2, ct=1.0)
             * code_value              = 2.1    (from config_code.yaml, e.g. CT code 0601)
             / w_modifier              / 0.5    (inverse -- trainee modifier, from roster)
             / global_modifier         / 1.2    (inverse -- per-worker global, from roster)
```

### Walkthrough Example

```
Scenario: MR assignment, code 0601 (value 2.1), trainee (w=0.5), worker global=1.2

  skill       = 1.0                         (flat, always 1)
  * modality  = 1.0 * 1.2       = 1.2       (MR factor from config.yaml)
  * code      = 1.2 * 2.1       = 2.52      (code 0601 has value 2.1 for MR)
  / w_mod     = 2.52 / 0.5      = 5.04      (trainee gets double effective weight)
  / global    = 5.04 / 1.2      = 4.2       (worker reduced capacity)
                                  ===
  final_weight = 4.2
```

### Comparison to Current Formula

```
CURRENT:   skill_weight * modality_factor                / w_modifier / global_modifier
NEW:       1.0          * modality_factor * code_value   / w_modifier / global_modifier
            ^-- forced 1                   ^-- NEW
```

Only two differences:
1. `skill_weight` is always **1.0** (no per-skill weighting).
2. `code_value` is a **new multiplier** from the selected 4-digit code.

### Modifier Direction Summary

| Factor | Direction | Example | Effect |
|---|---|---|---|
| `skill_weight` | multiply | 1.0 | always 1, no effect |
| `modality_factor` | multiply | 1.2 | MR counts 20% more |
| `code_value` | multiply | 2.1 | code makes it heavier |
| `w_modifier` | **divide** (inverse) | 0.5 | trainee: dividing by 0.5 = x2 effective weight |
| `global_modifier` | **divide** (inverse) | 1.2 | reduced capacity: dividing by 1.2 = less throughput |

---

## `config_code.yaml` -- Separate Code File

### Structure

Codes are grouped **per modality**. Each modality has its own list of ~100 codes. Codes **can overlap** between modalities (same code number, different multiplier).

```yaml
# config_code.yaml
# 4-digit modality codes with weight multipliers
# Organized per modality -- codes can appear in multiple modalities with different values

ct:
  "0601":
    label: "Abdomen Spezial"
    value: 2.1
  "0602":
    label: "Abdomen Standard"
    value: 1.0
  "0301":
    label: "Thorax Komplex"
    value: 1.8
  "0302":
    label: "Thorax Standard"
    value: 1.0
  "0701":
    label: "Neuro Komplex"
    value: 1.5
  # ... ~100 codes total for CT

mr:
  "0601":
    label: "Abdomen Spezial"
    value: 2.0          # same code, different value than CT
  "0602":
    label: "Abdomen Standard"
    value: 1.2
  "0701":
    label: "Neuro Komplex"
    value: 2.5           # MR neuro weighted higher than CT neuro
  # ... ~100 codes total for MR

xray:
  "1001":
    label: "Thorax ap/lat"
    value: 1.0
  "1002":
    label: "Abdomen leer"
    value: 1.0
  # ... ~100 codes total for X-ray

mammo:
  "2001":
    label: "Screening beidseits"
    value: 1.0
  "2002":
    label: "Diagnostisch"
    value: 1.5
  # ... ~100 codes total for Mammo
```

### Key Design Decisions

- **Per-modality grouping:** Codes are scoped to a modality. The popup only shows codes for the current modality.
- **Overlap allowed:** Code `0601` can exist in both CT and MR with different values.
- **Simple value:** Each code has one `value` (float multiplier), not a nested per-modality map.
- **Default:** If no code is selected, `code_value = 1.0`.

---

## Current Assignment Flow (before change)

Understanding the exact flow that needs to be modified:

```
User clicks skill button (e.g. "aou" on CT page)
  │
  ▼
index.html: onclick="getNextAssignment('aou', 'Abd-Onco')"
  │
  ▼
JS: fetch(`/api/${currentModality}/${encodedSkill}`)        ← GET /api/ct/aou
  │
  ▼
routes.py: assign_worker_api(modality, role)                ← line 1462
  │
  ▼
routes.py: _assign_worker(modality, role)                   ← line 1376
  │
  ├─ get_next_available_worker(now, role, modality, ...)    ← balancer.py:607
  │    └─ _get_worker_exclusion_based(...)                  ← balancer.py:350
  │         └─ weighted_ratio() uses get_global_weighted_count()
  │
  ├─ update_global_assignment(person, skill, modality, is_weighted)  ← balancer.py:86
  │    └─ weight = get_skill_modality_weight(role, modality) * (1.0 / combined_modifier)
  │                └─ config.py:397  →  skill_weight * modality_factor
  │
  └─ Response JSON: { selected_person, canonical_id, skill_used, is_weighted }
```

### New Flow (with code popup)

```
User clicks skill button (e.g. "aou" on CT page)
  │
  ▼
JS: getNextAssignment('aou', 'Abd-Onco')
  │
  ▼                                                          ← NEW
JS: if weight_mode == "modality_code":
  │   show popup with codes for current modality
  │   user selects code (e.g. "0601")
  │   OR user dismisses → code = null (value 1.0)
  │
  ▼
JS: fetch(`/api/${currentModality}/${encodedSkill}?code=0601`)   ← code as query param
  │
  ▼
routes.py: _assign_worker(modality, role)
  │   code = request.args.get('code')                        ← NEW: read code param
  │
  ├─ get_next_available_worker(now, role, modality, ...)     ← unchanged
  │
  ├─ update_global_assignment(person, skill, modality, is_weighted, code=code)  ← NEW param
  │    └─ weight = get_skill_modality_weight(role, modality, code) * (1.0 / combined_modifier)
  │                └─ config.py:  1.0 * modality_factor * code_value
  │
  └─ Response JSON: { ..., code: "0601", code_value: 2.1 }  ← NEW fields
```

---

## Detailed Code Changes

### 1. `config.py` -- Weight Calculation

**File:** `config.py`
**Current function:** `get_skill_modality_weight()` at line 397

```python
# --- CURRENT ---
def get_skill_modality_weight(skill: str, modality: str) -> float:
    modality_overrides = skill_modality_overrides.get(modality, {})
    if skill in modality_overrides:
        return coerce_float(modality_overrides[skill], 1.0)
    return skill_weights.get(skill, 1.0) * modality_factors.get(modality, 1.0)
```

```python
# --- NEW ---
# Add at module level (after APP_CONFIG):
WEIGHT_MODE = APP_CONFIG.get('weight_mode', 'default')  # from raw_config

def _load_code_config() -> dict:
    """Load config_code.yaml if weight_mode is 'modality_code'."""
    if WEIGHT_MODE != 'modality_code':
        return {}
    try:
        with open('config_code.yaml', 'r', encoding='utf-8') as f:
            return yaml.safe_load(f) or {}
    except FileNotFoundError:
        selection_logger.warning("weight_mode='modality_code' but config_code.yaml not found")
        return {}
    except Exception as exc:
        selection_logger.warning("Failed to load config_code.yaml: %s", exc)
        return {}

CODE_CONFIG = _load_code_config()

def get_code_value(modality: str, code: str) -> float:
    """Get multiplier for a 4-digit code within a modality. Returns 1.0 if not found."""
    entry = CODE_CONFIG.get(modality, {}).get(code, {})
    return coerce_float(entry.get('value', 1.0), 1.0)

def get_codes_for_modality(modality: str) -> dict:
    """Get all available codes for a modality (for popup UI)."""
    return CODE_CONFIG.get(modality, {})

def get_skill_modality_weight(skill: str, modality: str, code: str = None) -> float:
    """
    Get the weight for a skill x modality combination.

    In 'modality_code' mode:
      - All skill weights are 1.0
      - skill_modality_overrides are ignored
      - code_value from config_code.yaml is applied

    In 'default' mode:
      - Existing behavior unchanged
    """
    if WEIGHT_MODE == 'modality_code':
        base = 1.0  # all skills = 1
        modality_factor = modality_factors.get(modality, 1.0)
        code_multiplier = get_code_value(modality, code) if code else 1.0
        return base * modality_factor * code_multiplier

    # Default mode: existing logic
    modality_overrides = skill_modality_overrides.get(modality, {})
    if skill in modality_overrides:
        return coerce_float(modality_overrides[skill], 1.0)
    return skill_weights.get(skill, 1.0) * modality_factors.get(modality, 1.0)
```

**Also need:** Add `weight_mode` to `_build_app_config()` so it's available:
```python
# In _build_app_config(), add:
config['weight_mode'] = raw_config.get('weight_mode', 'default')
```

### 2. `balancer.py` -- Pass Code Through

**File:** `balancer.py`
**Function:** `update_global_assignment()` at line 86

```python
# --- CURRENT (line 132) ---
weight = get_skill_modality_weight(role, modality) * (1.0 / combined_modifier)
```

```python
# --- NEW ---
def update_global_assignment(person, role, modality, is_weighted=False, code=None):
    # ... existing modifier logic stays the same ...
    weight = get_skill_modality_weight(role, modality, code=code) * (1.0 / combined_modifier)
    #                                                  ^-- new param
    # ... rest unchanged ...
```

**Also:** `get_modality_weighted_count()` at line 43 -- this recalculates from raw counts and does NOT have access to the code that was used. For the load monitor display, we need to either:
- (a) Store the code per assignment so we can recalculate, OR
- (b) Store the already-computed weighted count directly (simpler)

**Recommendation:** Store the weighted count directly (option b). The current system already stores `weighted_counts` in `global_worker_data` -- this is already updated in `update_global_assignment()` at line 135. The `get_modality_weighted_count()` function at line 43 recalculates from skill counts, which would lose the code multiplier. We need to also store per-modality weighted counts directly.

```python
# NEW: In update_global_assignment(), after line 136, also store per-modality weight:
if 'weighted_counts_per_mod' not in global_worker_data:
    global_worker_data['weighted_counts_per_mod'] = {}
mod_counts = global_worker_data['weighted_counts_per_mod'].setdefault(modality, {})
mod_counts[canonical_id] = mod_counts.get(canonical_id, 0.0) + weight
```

Then `get_modality_weighted_count()` can use this when in code mode:
```python
def get_modality_weighted_count(canonical_id: str, modality: str) -> float:
    # In modality_code mode, use stored weighted counts (code info baked in)
    if WEIGHT_MODE == 'modality_code':
        return global_worker_data.get('weighted_counts_per_mod', {}).get(modality, {}).get(canonical_id, 0.0)

    # Default mode: recalculate from raw skill counts (existing logic)
    assignments = global_worker_data['assignments_per_mod'].get(modality, {}).get(canonical_id, {})
    if not assignments:
        return 0.0
    total_weight = 0.0
    for skill in SKILL_COLUMNS:
        count = assignments.get(skill, 0)
        if count > 0:
            weight = get_skill_modality_weight(skill, modality)
            total_weight += count * weight
    return total_weight
```

### 3. `routes.py` -- Accept Code Parameter + New API Endpoint

**File:** `routes.py`

#### 3a. Modify `_assign_worker()` (~line 1376)

```python
# Read code from query params
code = request.args.get('code')  # e.g. "0601" or None

# Pass to update_global_assignment:
canonical_id = update_global_assignment(person, actual_skill, actual_modality, is_weighted, code=code)

# Include in response:
response_data = {
    "selected_person": person,
    "canonical_id": canonical_id,
    "source_modality": actual_modality,
    "skill_used": actual_skill,
    "is_weighted": is_weighted,
    "code": code,                                      # NEW
    "code_value": get_code_value(actual_modality, code) if code else None,  # NEW
}
```

#### 3b. New API endpoint for code list

```python
from config import get_codes_for_modality, WEIGHT_MODE

@routes.route('/api/codes/<modality>', methods=['GET'])
@access_required
def get_modality_codes(modality: str):
    """Return all available codes for a modality (for popup UI)."""
    modality = normalize_modality(modality)
    codes = get_codes_for_modality(modality)
    return jsonify({
        "modality": modality,
        "codes": {
            code: {"label": data.get("label", ""), "value": data.get("value", 1.0)}
            for code, data in codes.items()
        }
    })
```

#### 3c. Expose weight_mode to templates

In the route that renders `index.html` (~line 1066), add `weight_mode` to template context:
```python
return render_template('index.html', ..., weight_mode=WEIGHT_MODE)
```

### 4. `templates/index.html` -- Popup UI

**File:** `templates/index.html`

#### 4a. Add popup HTML (after the button grid, ~line 375)

```html
<!-- Code selection popup (only rendered when weight_mode = modality_code) -->
{% if weight_mode == 'modality_code' %}
<div id="codePopup" class="code-popup-overlay" style="display:none;">
  <div class="code-popup">
    <div class="code-popup-header">
      <h3>Code waehlen</h3>
      <input type="text" id="codeSearchInput" placeholder="Code oder Bezeichnung suchen..."
             class="code-search-input" oninput="filterCodes(this.value)">
    </div>
    <div class="code-popup-list" id="codeList">
      <!-- populated by JS -->
    </div>
    <div class="code-popup-footer">
      <button class="btn-cancel" onclick="dismissCodePopup()">Abbrechen (x1.0)</button>
    </div>
  </div>
</div>
{% endif %}
```

#### 4b. Add CSS for popup

```css
.code-popup-overlay {
  position: fixed; top: 0; left: 0; width: 100%; height: 100%;
  background: rgba(0,0,0,0.5); z-index: 1000;
  display: flex; align-items: center; justify-content: center;
}
.code-popup {
  background: #fff; border-radius: 12px; width: 90%; max-width: 500px;
  max-height: 80vh; display: flex; flex-direction: column;
}
.code-popup-header { padding: 1rem; border-bottom: 1px solid #eee; }
.code-popup-header h3 { margin-bottom: 0.5rem; }
.code-search-input {
  width: 100%; padding: 0.5rem; border: 1px solid #ccc; border-radius: 6px;
  font-size: 1rem;
}
.code-popup-list {
  overflow-y: auto; flex: 1; padding: 0.5rem;
}
.code-item {
  padding: 0.75rem 1rem; cursor: pointer; border-radius: 6px;
  display: flex; justify-content: space-between; align-items: center;
}
.code-item:hover { background: #f0f4ff; }
.code-item-id { font-weight: 700; font-family: monospace; }
.code-item-label { flex: 1; margin-left: 1rem; }
.code-item-value { font-weight: 600; color: #2f5d8a; }
.code-popup-footer { padding: 1rem; border-top: 1px solid #eee; text-align: center; }
```

#### 4c. Modify JS assignment function

```javascript
// Current:
function getNextAssignment(skillSlug, skillLabel, forcePrimary = false) {
  if (requestInProgress) return;
  lastSkillUsed = skillLabel || skillSlug;
  setButtonsDisabled(true);
  const encodedSkill = encodeURIComponent(skillSlug);
  const endpoint = forcePrimary
    ? `/api/${currentModality}/${encodedSkill}/strict`
    : `/api/${currentModality}/${encodedSkill}`;
  fetch(endpoint) ...
}

// NEW:
const weightMode = '{{ weight_mode | default("default") }}';
let pendingAssignment = null;  // { skillSlug, skillLabel, forcePrimary }

function getNextAssignment(skillSlug, skillLabel, forcePrimary = false) {
  if (requestInProgress) return;

  if (weightMode === 'modality_code') {
    // Show code popup instead of immediate assignment
    pendingAssignment = { skillSlug, skillLabel, forcePrimary };
    showCodePopup();
    return;
  }

  // Default mode: direct assignment (unchanged)
  executeAssignment(skillSlug, skillLabel, forcePrimary, null);
}

function executeAssignment(skillSlug, skillLabel, forcePrimary, code) {
  lastSkillUsed = skillLabel || skillSlug;
  setButtonsDisabled(true);
  const encodedSkill = encodeURIComponent(skillSlug);
  let endpoint = forcePrimary
    ? `/api/${currentModality}/${encodedSkill}/strict`
    : `/api/${currentModality}/${encodedSkill}`;
  if (code) {
    endpoint += `${endpoint.includes('?') ? '&' : '?'}code=${encodeURIComponent(code)}`;
  }
  fetch(endpoint) ...   // rest unchanged
}

// Popup management
let modalityCodes = null;  // cached after first fetch

async function showCodePopup() {
  if (!modalityCodes) {
    const resp = await fetch(`/api/codes/${currentModality}`);
    const data = await resp.json();
    modalityCodes = data.codes;
  }
  renderCodeList(modalityCodes);
  document.getElementById('codePopup').style.display = 'flex';
  document.getElementById('codeSearchInput').value = '';
  document.getElementById('codeSearchInput').focus();
}

function renderCodeList(codes) {
  const list = document.getElementById('codeList');
  list.innerHTML = '';
  for (const [code, info] of Object.entries(codes)) {
    const item = document.createElement('div');
    item.className = 'code-item';
    item.innerHTML = `
      <span class="code-item-id">${code}</span>
      <span class="code-item-label">${info.label}</span>
      <span class="code-item-value">x${info.value}</span>
    `;
    item.onclick = () => selectCode(code);
    list.appendChild(item);
  }
}

function filterCodes(query) {
  const q = query.toLowerCase();
  const filtered = {};
  for (const [code, info] of Object.entries(modalityCodes)) {
    if (code.includes(q) || info.label.toLowerCase().includes(q)) {
      filtered[code] = info;
    }
  }
  renderCodeList(filtered);
}

function selectCode(code) {
  document.getElementById('codePopup').style.display = 'none';
  if (pendingAssignment) {
    const { skillSlug, skillLabel, forcePrimary } = pendingAssignment;
    pendingAssignment = null;
    executeAssignment(skillSlug, skillLabel, forcePrimary, code);
  }
}

function dismissCodePopup() {
  document.getElementById('codePopup').style.display = 'none';
  if (pendingAssignment) {
    const { skillSlug, skillLabel, forcePrimary } = pendingAssignment;
    pendingAssignment = null;
    executeAssignment(skillSlug, skillLabel, forcePrimary, null);  // code=null → value 1.0
  }
}
```

### 5. Result Display -- Show Code on Assignment Card

In the result panel section of `index.html`, where the assignment result is shown:

```javascript
// In the fetch().then() handler that displays results:
if (data.code) {
  // Show code badge next to selected person
  resultEl.innerHTML += ` <span class="code-badge">${data.code} (x${data.code_value})</span>`;
}
```

```css
.code-badge {
  display: inline-block; background: #2f5d8a; color: #fff;
  padding: 0.1rem 0.5rem; border-radius: 4px; font-size: 0.85rem;
  font-family: monospace; margin-left: 0.5rem;
}
```

### 6. Worker Load Monitor -- Show Code Impact

**File:** `routes.py` (worker-load endpoint, ~line 1620)

The `/api/worker-load` endpoint already returns `global_weight` and per-modality weights. With the `weighted_counts_per_mod` stored in `global_worker_data`, the modality-level weights will automatically include the code multiplier impact. No change needed to the endpoint, but the monitor will reflect accurate weights.

### 7. State Persistence

**File:** `state_manager.py`

Ensure `weighted_counts_per_mod` is included in `save_state()` / `load_state()` so code-weighted counts survive restarts.

---

## Config Changes

### `config.yaml` (minimal addition)

```yaml
# Add ONE flag to existing config.yaml -- everything else stays untouched
weight_mode: "modality_code"   # Options: "default" | "modality_code"
```

When `weight_mode: "modality_code"`:
- All skill weights from `skills:` section are ignored (treated as 1.0).
- `skill_modality_overrides:` are ignored.
- `config_code.yaml` is loaded and codes become available in the UI.
- Modality `factor:` values are still used.
- Worker modifiers (`global_modifier`, `modifier`) are still used.

When `weight_mode: "default"` (or not set):
- Everything works exactly as today. `config_code.yaml` is not loaded.

### New File: `config_code.yaml`

- Lives next to `config.yaml` in the project root.
- Loaded only when `weight_mode: "modality_code"`.
- Structure as shown in the `config_code.yaml` section above.

---

## File Change Summary

| File | Change | Lines Affected |
|---|---|---|
| `config.yaml` | Add `weight_mode` key | +1 line |
| `config_code.yaml` | **NEW FILE** -- code definitions per modality | ~400+ lines (100 codes x 4 mods) |
| `config.py` | Add `WEIGHT_MODE`, `CODE_CONFIG`, `get_code_value()`, `get_codes_for_modality()`; modify `get_skill_modality_weight()` and `_build_app_config()` | ~40 new lines, ~10 modified |
| `balancer.py` | Add `code` param to `update_global_assignment()`; store `weighted_counts_per_mod`; update `get_modality_weighted_count()` | ~15 modified lines |
| `routes.py` | Read `code` query param in `_assign_worker()`; pass to balancer; add `/api/codes/<modality>` endpoint; pass `weight_mode` to template | ~25 new lines, ~5 modified |
| `templates/index.html` | Add popup HTML/CSS; modify JS `getNextAssignment()` to show popup; add `executeAssignment()`, `showCodePopup()`, `selectCode()`, `dismissCodePopup()`, `filterCodes()` | ~120 new lines |
| `state_manager.py` | Include `weighted_counts_per_mod` in save/load | ~5 lines |

**Total: ~200 new lines, ~30 modified lines. 1 new file.**

---

## Implementation Steps

### Phase 1: Backend (config + weight logic)
- [ ] Add `weight_mode` to `_build_app_config()` in `config.py`
- [ ] Add `_load_code_config()`, `CODE_CONFIG`, `WEIGHT_MODE` to `config.py`
- [ ] Add `get_code_value()` and `get_codes_for_modality()` to `config.py`
- [ ] Modify `get_skill_modality_weight()` to branch on `WEIGHT_MODE`
- [ ] Create `config_code.yaml` with example/placeholder codes per modality

### Phase 2: Balancer (pass code through)
- [ ] Add `code` param to `update_global_assignment()` in `balancer.py`
- [ ] Pass `code` into `get_skill_modality_weight()` call at line 132
- [ ] Add `weighted_counts_per_mod` storage in `update_global_assignment()`
- [ ] Update `get_modality_weighted_count()` to use stored counts in code mode
- [ ] Include `weighted_counts_per_mod` in state persistence (`state_manager.py`)

### Phase 3: Routes (API changes)
- [ ] Read `code` query param in `_assign_worker()` in `routes.py`
- [ ] Pass `code` to `update_global_assignment()`
- [ ] Include `code` and `code_value` in assignment response JSON
- [ ] Add `/api/codes/<modality>` endpoint
- [ ] Pass `weight_mode` to `index.html` template context

### Phase 4: Frontend (popup UI)
- [ ] Add popup overlay HTML to `index.html` (conditional on `weight_mode`)
- [ ] Add popup CSS styles
- [ ] Modify `getNextAssignment()` to intercept and show popup in code mode
- [ ] Add `executeAssignment()` function (extracted from current logic)
- [ ] Add `showCodePopup()` -- fetch + render codes
- [ ] Add `selectCode()` / `dismissCodePopup()` handlers
- [ ] Add `filterCodes()` search/filter
- [ ] Show code badge on assignment result card

### Phase 5: Testing + Data
- [ ] Add unit tests for `get_skill_modality_weight()` in both modes
- [ ] Add unit tests for `get_code_value()` with valid/missing/unknown codes
- [ ] Add integration test for assignment flow with code param
- [ ] Test popup UI with ~100 codes (scrolling, search, selection)
- [ ] Test dismiss popup → code_value = 1.0
- [ ] Test state persistence across restart (weighted_counts_per_mod)
- [ ] Get final code lists (~100 per modality) from customer
- [ ] Populate `config_code.yaml` with customer data

---

## Open Questions

1. **Complete code lists:** Customer needs to provide all 4-digit codes per modality with their multiplier values.
2. **Code filtering by skill:** Should certain codes only appear for certain skills, or are all codes available for every skill within a modality?
3. **Persistence:** Should the last-used code be remembered per skill-modality combo, or selected fresh each assignment?
4. **Reporting:** Does the customer need weight reports broken down by code?
5. **Code management UI:** Should there be an admin page to edit `config_code.yaml` codes, or is file editing sufficient?
6. **Fallback behavior:** If `config_code.yaml` is missing but `weight_mode` is set, should we warn and fall back to default mode, or error?
7. **Usage stats:** Should the `usage_logger` also record which code was selected per assignment?
