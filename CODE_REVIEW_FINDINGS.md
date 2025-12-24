# Code Review Findings - RadIMO Cortex

**Review Date**: 2025-12-24
**Reviewer**: Claude Code Review
**Scope**: Full codebase review for bugs and legacy code

---

## Executive Summary

| Severity | Count |
|----------|-------|
| **CRITICAL** | 2 |
| **HIGH** | 6 |
| **MEDIUM** | 8 |
| **LOW** | 7 |

---

## CRITICAL Issues

### 1. Startup Initialization Not Called in Production (app.py:97)

**Location**: `app.py:97`

**Issue**: When running with Gunicorn (production), the `startup_initialization()` function is never called because it's inside `if __name__ == '__main__':` block.

```python
if __name__ == '__main__':
    startup_initialization()  # NEVER CALLED when imported by gunicorn
    app.run(...)
```

**Impact**: In production, the application starts without:
- Loading saved state from `fairness_state.json`
- Loading backup Excel files for modalities
- Proper initialization of worker data

**Fix**: Move `startup_initialization()` outside the `if __name__` block or use Flask's `before_first_request` decorator.

---

### 2. KeyError Risk in Assignment Recording (balancer.py:93)

**Location**: `balancer.py:93`

**Issue**: If an invalid `role` is passed that isn't in `SKILL_COLUMNS`, the code will crash with KeyError.

```python
def _get_or_create_assignments(modality: str, canonical_id: str) -> dict:
    # ... only initializes skills from SKILL_COLUMNS
    assignments[canonical_id] = {skill: 0 for skill in SKILL_COLUMNS}

# Later in update_global_assignment:
assignments[role] += 1  # KeyError if role not in SKILL_COLUMNS!
```

**Impact**: Server crash on invalid API request.

**Fix**: Add validation or use `.get()` with default:
```python
if role in SKILL_COLUMNS:
    assignments[role] = assignments.get(role, 0) + 1
```

---

## HIGH Priority Issues

### 3. Thread Safety - Race Conditions (data_manager.py)

**Location**: Multiple locations in `data_manager.py`

**Issue**: The `lock` is defined at line 48 but not consistently used when modifying global state.

**Affected operations**:
- `global_worker_data['weighted_counts']` modifications in `balancer.py:89-90`
- `modality_data[modality]` modifications in multiple functions
- `save_state()` called without lock protection

**Impact**: Potential data corruption under concurrent requests.

**Fix**: Wrap all state modifications in `with lock:` blocks consistently.

---

### 4. Skill Value Lost After Excel Load (data_manager.py:493)

**Location**: `data_manager.py:493`

**Issue**: When loading from Excel, skill columns are cast to int, losing the 'w' marker:

```python
for skill in SKILL_COLUMNS:
    if skill not in df.columns:
        df[skill] = 0
    df[skill] = df[skill].fillna(0).astype(int)  # 'w' becomes 0 or NaN!
```

**Impact**: Weighted skill assignments (`w`) are lost after server restart or Excel reload.

**Fix**: Use `normalize_skill_value()` instead of `.astype(int)`:
```python
df[skill] = df[skill].fillna(0).apply(normalize_skill_value)
```

---

### 5. Hardcoded Security Defaults (config.py:36-38)

**Location**: `config.py:36-38`

**Issue**: Security-sensitive defaults are hardcoded:

```python
DEFAULT_ADMIN_PASSWORD = 'change_pw_for_live'
DEFAULT_ACCESS_PASSWORD = 'change_easy_pw'
DEFAULT_SECRET_KEY = 'super_secret_key_for_dev'
```

**Impact**: If config.yaml is missing or incomplete, the app runs with known credentials.

**Fix**:
- Fail loudly if passwords aren't configured in production
- Use environment variables for secrets
- Add startup check that warns/fails on default passwords

---

### 6. Missing CSRF Protection (routes.py)

**Location**: All POST routes

**Issue**: Flask forms don't have CSRF token validation. All POST endpoints are vulnerable to CSRF attacks.

**Impact**: Attackers could trick authenticated admins into performing unwanted actions.

**Fix**:
- Use Flask-WTF extension with CSRF protection
- Add CSRF tokens to all forms

---

### 7. Skill Name Parsing Bug in Usage Logger (lib/usage_logger.py:104)

**Location**: `lib/usage_logger.py:104`

**Issue**: If a skill name contains an underscore, the parsing logic fails:

```python
parts = column.rsplit('_', 1)  # "Some_Skill_ct" -> ["Some_Skill", "ct"] ✓
                               # But stored as ("Some_Skill", "ct")
                               # If skill is "Notfall_Extra", parsing breaks
```

**Impact**: Incorrect statistics for skills with underscores in names.

**Fix**: Store the key tuple directly or use a different separator.

---

### 8. Empty Modality Check Missing (routes.py:267-268)

**Location**: `routes.py:267-268`

**Issue**: Accessing `modality_data[mod]` without checking if mod exists:

```python
for mod in target_modalities:
    df = modality_data[mod]['working_hours_df']  # KeyError if invalid mod
```

**Impact**: Server error on invalid modality parameter.

**Fix**: Add validation or use `.get()` with default.

---

## MEDIUM Priority Issues

### 9. Pandas Boolean Comparison Style (balancer.py:108, data_manager.py:349)

**Location**: Multiple files

**Issue**: Using `== True` instead of direct boolean:

```python
df_copy = df_copy[df_copy['counts_for_hours'] == True]
```

**Recommendation**: Use idiomatic pandas:
```python
df_copy = df_copy[df_copy['counts_for_hours']]
```

---

### 10. Import Inside Function (routes.py:1207)

**Location**: `routes.py:1207`

**Issue**: `import csv` inside `get_usage_stats_file_info()` function.

**Impact**: Minor performance hit, code smell.

**Fix**: Move to module-level imports.

---

### 11. Unused Import (gunicorn_config.py:2)

**Location**: `gunicorn_config.py:2`

**Issue**: `import multiprocessing` is imported but never used.

**Fix**: Remove unused import.

---

### 12. Date Parsing Edge Case (data_manager.py:319)

**Location**: `data_manager.py:319`

**Issue**: Assumes `fromisoformat()` returns a datetime, but could fail if format is unexpected:

```python
global_worker_data['last_reset_date'] = datetime.fromisoformat(last_reset_str).date()
```

**Fix**: Add try/except or validate format first.

---

### 13. Empty Except Blocks (multiple files)

**Locations**:
- `scripts/exam_values.py:206` - `pass` in except
- `lib/usage_logger.py:243` - Empty branch in conditional

**Issue**: Silent failure on errors.

**Fix**: At minimum, log the exception.

---

### 14. Magic Strings (TIME_FORMAT)

**Location**: Throughout codebase

**Issue**: Time format `'%H:%M'` repeated in multiple places instead of using `TIME_FORMAT` constant.

**Fix**: Use `TIME_FORMAT` constant from `lib/utils.py` consistently.

---

### 15. Comment Inconsistency (balancer.py:369)

**Location**: `balancer.py:367-369`

**Issue**: Comment says "floor" but code uses `max()`:

```python
# Use floor of 0.5 hours to prevent division by very small values
return w / max(h, 0.5)  # This is a minimum/threshold, not floor
```

**Fix**: Correct the comment.

---

### 16. Long Functions

**Locations**:
- `_get_worker_exclusion_based()`: ~200 lines
- `build_working_hours_from_medweb()`: ~300 lines
- `_add_gap_to_schedule()`: ~150 lines

**Recommendation**: Consider breaking into smaller, testable functions.

---

## LOW Priority Issues

### 17. Inconsistent Lock Usage in save_state (data_manager.py:273)

**Location**: `data_manager.py:273`

**Issue**: `save_state()` writes to file without lock protection.

---

### 18. Duplicate Import Pattern (routes.py:294, 301, 321)

**Location**: `routes.py`

**Issue**: Imports from `data_manager` inside functions:

```python
from data_manager import build_valid_skills_map  # Inside function
```

**Recommendation**: Import at module level.

---

### 19. Inconsistent Error Messages (German/English Mix)

**Location**: Throughout codebase

**Issue**: Error messages mix German and English:
- `"Falsches Passwort"` vs `"Invalid modality"`

**Recommendation**: Standardize on one language or use i18n.

---

### 20. Missing Type Hints in Some Functions

**Location**: Various

**Issue**: Some newer functions lack type hints while others have them.

**Recommendation**: Add type hints consistently.

---

### 21. Debug HTML in Production (routes.py:567)

**Location**: `routes.py:567`

**Issue**: `df.to_html()` exposed in admin view - could leak sensitive data structure.

---

### 22. Session Cookie Security

**Location**: `app.py:33`

**Issue**: 365-day session lifetime is quite long for security-sensitive app.

**Recommendation**: Consider shorter lifetime or implement session rotation.

---

### 23. No Input Length Validation

**Location**: Various API endpoints

**Issue**: No maximum length validation on string inputs could lead to memory issues.

---

## Legacy Code Candidates for Removal

### Files/Code to Review for Removal:

1. **Duplicate backup file references**:
   - Both `default_file_path` and `scheduled_file_path` exist but only one seems actively used

2. **Unused state tracking**:
   - `WeightedCounts` in `modality_data` vs `weighted_counts` in `global_worker_data` - appears redundant

3. **Old import patterns**:
   - Some imports are duplicated between module level and inside functions

---

## Recommendations Summary

### Immediate Actions (Critical/High):
1. Fix startup initialization for Gunicorn
2. Add role validation in `update_global_assignment()`
3. Fix skill value preservation on Excel load
4. Implement consistent locking for thread safety

### Short-term Actions (Medium):
5. Add CSRF protection
6. Fix skill name parsing in usage logger
7. Standardize boolean comparisons in pandas
8. Move all imports to module level

### Long-term Actions (Low):
9. Refactor long functions
10. Standardize error message language
11. Add comprehensive type hints
12. Improve test coverage

---

## Test Recommendations

Based on bugs found, prioritize testing for:

1. **Concurrent access scenarios** - Multiple simultaneous assignment requests
2. **Edge cases in shift handling** - Overnight shifts, gaps spanning midnight
3. **Invalid input handling** - Malformed modality/skill names
4. **State persistence** - Server restart recovery
5. **Date boundary behavior** - Daily reset at 07:30

---

*Report generated by automated code review. Manual verification recommended for all findings.*
