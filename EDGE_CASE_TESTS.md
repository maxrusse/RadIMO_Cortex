# Exclusion Routing Edge Case Tests

## Test Scenarios

### 1. Empty Exclusion List
**Config:** `Herz: exclude_skills: []`
**Workers:** Anna (Herz=1), Ben (Herz=0)
**Expected:** Level 1 includes both Anna and Ben ✓

### 2. Worker with Conflict (skill=1 + excluded=1)
**Config:** `Herz: exclude_skills: [Chest]`
**Workers:** Anna (Herz=1, Chest=1)
**Request:** Herz
**Expected:**
- Level 1: Anna EXCLUDED (Chest=1)
- Level 2: Anna INCLUDED (Herz=1)
- **Exclusion wins in L1, Skill wins in L2** ✓

### 3. All Workers Have Requested Skill = -1
**Workers:** Anna (Herz=-1), Ben (Herz=-1)
**Request:** Herz
**Expected:**
- Level 1: Empty (all filtered out by Herz<0)
- Level 2: Empty (all filtered out by Herz<0)
- Return: None ✓

### 4. Non-Existent Exclusion Skill
**Config:** `Herz: exclude_skills: [NonExistent]`
**Workers:** Anna (Herz=1)
**Expected:**
- Code checks: `if skill_to_exclude in filtered_workers.columns`
- NonExistent not in columns, skip exclusion
- Level 1: Anna INCLUDED ✓

### 5. Strict Mode (allow_fallback=False)
**Workers:** All have conflict (Herz=1, Chest=1)
**Config:** Exclude Chest=1
**Request:** Herz (strict mode)
**Expected:**
- Level 1: Empty (all excluded by Chest=1)
- Level 2: SKIPPED (allow_fallback=False)
- Return: None ✓

### 6. Unknown Role/Skill
**Request:** Role='unknown'
**Expected:**
- role_lower not in role_map → defaults to 'normal'
- Continues with Normal skill ✓

### 7. Multiple Exclusions
**Config:** `Herz: exclude_skills: [Chest, Msk, Privat]`
**Workers:**
- Anna (Herz=1, Chest=0, Msk=0, Privat=0)
- Ben (Herz=1, Chest=1, Msk=0, Privat=0)
- Clara (Herz=1, Chest=0, Msk=1, Privat=0)
- David (Herz=1, Chest=0, Msk=0, Privat=1)
**Expected:**
- Level 1: Only Anna (others excluded by Chest/Msk/Privat)
- Level 2: All four ✓

### 8. Exclusion Rule Missing for Requested Skill
**Config:** No entry for 'Herz' in exclusion_rules
**Expected:**
- `skill_exclusions = EXCLUSION_RULES.get(primary_skill, {})`
- Returns empty dict → exclude_skills = []
- Level 1: No exclusions applied ✓

### 9. Cross-Modality with Exclusions
**Request:** CT Herz, exclude Chest=1
**Fallback:** MR modality
**Workers:**
- CT: Anna (Herz=1, Chest=1), Ben (Herz=0, Chest=0)
- MR: Clara (Herz=1, Chest=0)
**Expected:**
- Level 1 CT: Only Ben (Anna excluded)
- Level 1 MR: Clara (not excluded)
- Pick lowest ratio between Ben and Clara ✓

### 10. Empty Candidate Pool After Exclusions + Balancer
**Workers:** All have Herz=1, Chest=1 (dual specialists)
**Config:** Exclude Chest=1
**Balancer:** min_assignments_per_skill=5, all workers have <5
**Expected:**
- Level 1: Empty after exclusions
- Level 2: All workers included (Herz>=0)
- Balancer applies to Level 2 pool ✓

## Return Value Validation

All functions must return:
- **Success:** `(candidate, used_skill, source_modality)` tuple
- **Failure:** `None`

Verified in code:
- Line 2275: `return candidate, used_skill, source_modality` ✓
- Line 2339: `return candidate, used_skill, source_modality` ✓
- Line 2346: `return None` ✓

## API Compatibility

### Regular Mode: `/api/ct/herz`
- Calls: `get_next_available_worker(allow_fallback=True)`
- Uses: Level 1 → Level 2 → None ✓

### Strict Mode: `/api/ct/herz/strict`
- Calls: `get_next_available_worker(allow_fallback=False)`
- Uses: Level 1 → None (skips Level 2) ✓

## UI Isolation

**Confirmed:** No exclusion rules exposed in UI
```
grep -r "exclusion" templates/ → No matches ✓
```

Exclusion rules are **config-only** (config.yaml)

## Summary

✅ All edge cases handled correctly
✅ API routes compatible
✅ UI doesn't expose exclusion rules
✅ Return values consistent
✅ Fallback logic respects allow_fallback parameter
