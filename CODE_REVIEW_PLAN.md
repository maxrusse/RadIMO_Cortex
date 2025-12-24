# Deep Code Review Plan - RadIMO Cortex

## Overview

This document outlines a comprehensive plan for conducting a deep code review of the RadIMO Cortex codebase, focusing on:
- **Bug detection** - Logic errors, edge cases, race conditions
- **Legacy code cleanup** - Dead code, deprecated patterns, unused components
- **Code quality** - Maintainability, consistency, best practices

---

## Codebase Summary

| Module | LOC | Priority | Description |
|--------|-----|----------|-------------|
| `data_manager.py` | 1,800 | **HIGH** | State management, data loading, persistence |
| `routes.py` | 1,233 | **HIGH** | API endpoints, route handlers, authentication |
| `balancer.py` | 492 | **HIGH** | Load balancing algorithm, worker assignment |
| `config.py` | 350 | MEDIUM | Configuration loading, validation |
| `lib/utils.py` | ~150 | MEDIUM | Utility functions, type coercion |
| `lib/usage_logger.py` | ~100 | LOW | Usage statistics tracking |
| `app.py` | 100 | LOW | Flask initialization, scheduler |
| `scripts/*.py` | ~400 | LOW | Utility scripts |

---

## Phase 1: Critical Path Review (HIGH Priority)

### 1.1 Load Balancing Algorithm (`balancer.py`)

**Focus Areas:**
- [ ] `get_next_available_worker()` - Core selection logic
  - Edge case: All workers at capacity
  - Edge case: No workers with required skill
  - Fallback mechanism correctness
- [ ] Weight calculation accuracy
  - Skill weight × Modality factor × Worker modifier
  - Skill×Modality override handling
- [ ] Threshold logic
  - `imbalance_threshold_pct` calculations
  - Overflow disable windows (shift start/end)
- [ ] Global weighted count tracking
  - Race conditions in concurrent access
  - State consistency after updates

**Potential Bug Patterns:**
- Off-by-one errors in shift window calculations
- Float comparison issues in weight calculations
- Missing null checks for optional config values

---

### 1.2 Data Manager (`data_manager.py`)

**Focus Areas:**
- [ ] State management globals
  - `modality_data`, `staged_modality_data`, `global_worker_data`
  - Thread safety with concurrent requests
  - State consistency across operations
- [ ] CSV/Excel parsing
  - Error handling for malformed input
  - Date/time parsing edge cases
  - Encoding issues (UTF-8, special characters)
- [ ] Worker ID canonicalization
  - Name matching logic
  - Duplicate detection
- [ ] Shift duration calculations
  - Overnight shift handling (22:00-06:00)
  - GAP handling (split shifts)
  - Timezone edge cases
- [ ] File I/O operations
  - Error handling for missing files
  - Backup creation reliability
  - JSON persistence integrity

**Potential Bug Patterns:**
- DataFrame operations with empty DataFrames
- Index errors in data lookups
- Memory leaks with large datasets
- Race conditions in file writes

---

### 1.3 Routes and API (`routes.py`)

**Focus Areas:**
- [ ] API endpoints correctness
  - `/api/{modality}/{skill}` - normal assignment
  - `/api/{modality}/{skill}/strict` - strict mode
  - Response format consistency
- [ ] Input validation
  - URL parameter sanitization
  - Form data validation
  - File upload security
- [ ] Authentication/Authorization
  - Session management
  - Password verification
  - Access control consistency
- [ ] Error handling
  - HTTP error codes
  - User-facing error messages
  - Graceful degradation
- [ ] Data serialization
  - DataFrame to JSON conversion
  - Date/time formatting
  - Unicode handling

**Potential Bug Patterns:**
- Missing authentication on protected routes
- SQL/Command injection (if any DB operations)
- XSS vulnerabilities in templates
- CSRF protection gaps

---

## Phase 2: Configuration & Utilities (MEDIUM Priority)

### 2.1 Configuration Loading (`config.py`)

**Focus Areas:**
- [ ] YAML parsing error handling
- [ ] Default value completeness
- [ ] Type validation for config values
- [ ] Missing/optional config key handling
- [ ] Configuration hot-reload support

**Potential Bug Patterns:**
- KeyError for missing optional configs
- Type coercion errors (string vs int)
- Path resolution issues

---

### 2.2 Utility Functions (`lib/utils.py`)

**Focus Areas:**
- [ ] Type coercion functions
- [ ] Time handling utilities
- [ ] Normalization functions
- [ ] Edge case handling

---

## Phase 3: Legacy Code Detection

### 3.1 Dead Code Analysis

**Checklist:**
- [ ] Unused imports in each module
- [ ] Unused functions/methods
- [ ] Unreachable code paths
- [ ] Commented-out code blocks
- [ ] TODO/FIXME/HACK comments
- [ ] Debug print statements
- [ ] Deprecated function usage

### 3.2 Code Consistency

**Checklist:**
- [ ] Naming conventions (snake_case consistency)
- [ ] Docstring completeness
- [ ] Error message consistency
- [ ] Logging level appropriateness
- [ ] Return type consistency
- [ ] Parameter validation patterns

### 3.3 Deprecation Candidates

**Review for potential removal:**
- [ ] Backward compatibility code
- [ ] Feature flags for old behavior
- [ ] Migration code paths
- [ ] Legacy data format support

---

## Phase 4: Testing & Validation

### 4.1 Test Coverage Assessment

**Current State:**
- Test data exists in `test_data/` directory
- No formal test suite identified

**Recommendations:**
- [ ] Identify critical paths needing tests
- [ ] Document manual testing procedures
- [ ] Create test scenarios for edge cases

### 4.2 Static Analysis

**Tools to apply:**
- [ ] Python linting (flake8/pylint)
- [ ] Type checking (mypy) if type hints present
- [ ] Security scanning (bandit)
- [ ] Complexity analysis (radon)

---

## Review Execution Plan

### Step 1: Automated Checks
1. Run static analysis tools
2. Generate complexity reports
3. Identify obvious issues

### Step 2: Module-by-Module Review

| Order | Module | Focus |
|-------|--------|-------|
| 1 | `balancer.py` | Algorithm correctness, edge cases |
| 2 | `data_manager.py` | State management, data integrity |
| 3 | `routes.py` | API correctness, security |
| 4 | `config.py` | Validation, defaults |
| 5 | `lib/utils.py` | Utility correctness |
| 6 | `app.py` | Initialization, scheduler |
| 7 | `scripts/*.py` | Utility scripts |

### Step 3: Cross-Cutting Concerns
- Thread safety analysis
- Error handling consistency
- Logging completeness
- Security audit

### Step 4: Documentation & Reporting
- Document all findings
- Categorize by severity
- Propose fixes
- Create refactoring roadmap

---

## Severity Classification

| Severity | Description | Action |
|----------|-------------|--------|
| **CRITICAL** | Data loss, security vulnerability, system crash | Immediate fix |
| **HIGH** | Incorrect behavior, silent failures | Fix in current sprint |
| **MEDIUM** | Code smell, maintainability issue | Scheduled fix |
| **LOW** | Style issues, minor improvements | As time permits |

---

## Expected Outcomes

1. **Bug Report** - List of identified bugs with severity
2. **Legacy Code Report** - Dead code and deprecation candidates
3. **Refactoring Roadmap** - Prioritized cleanup tasks
4. **Security Assessment** - Potential vulnerabilities
5. **Code Quality Metrics** - Complexity, maintainability scores

---

## Next Steps

After plan approval, proceed with:
1. Execute automated static analysis
2. Begin module-by-module deep review
3. Document findings in structured format
4. Create actionable fix recommendations

