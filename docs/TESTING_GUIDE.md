# Testing Guide: Fallback Strategy APIs

## ✅ Health Check Results

### Configuration Status
- ✓ **fallback_strategy**: `skill_priority` (configured)
- ✓ **modality_fallbacks**: xray → [ct, mr], ct → [mr], mr → []
- ✓ **skill fallback chains**: All skills properly configured
- ✓ **balancer settings**: All parameters valid

### Code Structure Status
- ✓ **get_next_available_worker**: Dispatcher function exists
- ✓ **_get_worker_skill_priority**: Implemented
- ✓ **_get_worker_modality_priority**: Implemented
- ✓ **_get_worker_pool_priority**: Implemented
- ✓ **API endpoints**: All 3 endpoints found and correct
- ✓ **Strategy routing**: All three strategies properly routed

### Documentation Status
- ✓ **README.md**: All three strategies documented
- ✓ **Configuration examples**: Present
- ✓ **API surface**: Documented

---

## 🔧 API Endpoints

### 1. **Normal Assignment** (respects fallback_strategy)
```bash
GET /api/<modality>/<role>
```

**Example:**
```bash
curl http://localhost:5000/api/ct/herz
```

**Response:**
```json
{
  "Draw Time": "14:30:15",
  "Assigned Person": "Worker Name",
  "modality_requested": "ct",
  "modality_used": "ct",
  "skill_used": "Herz",
  "fallback_allowed": true,
  "strict_request": false,
  "Summe": {...},
  "Global": {...}
}
```

### 2. **Strict Assignment** (NO fallbacks)
```bash
GET /api/<modality>/<role>/strict
```

**Example:**
```bash
curl http://localhost:5000/api/xray/herz/strict
```

**Response:**
- Same format as above
- `fallback_allowed`: false
- `strict_request`: true
- Will return "Keine Person in dieser Gruppe verfügbar" if no exact match

### 3. **Quick Reload** (get current stats)
```bash
GET /api/quick_reload?modality=<modality>
```

**Example:**
```bash
curl http://localhost:5000/api/quick_reload?modality=ct
```

**Response:**
```json
{
  "Draw Time": "14:30:15",
  "Assigned Person": null,
  "Summe": {...},
  "Global": {...},
  "GlobalWeighted": {...},
  "available_buttons": {...},
  "operational_checks": {...}
}
```

---

## 🧪 Testing Each Strategy

### Test Setup
1. Start the Flask application:
   ```bash
   flask --app app run --debug
   ```

2. Open a second terminal for log monitoring:
   ```bash
   tail -f logs/selection.log
   ```

3. Open a third terminal for API calls

---

### Strategy 1: `skill_priority` (Default)

**Configuration:**
```yaml
balancer:
  fallback_strategy: skill_priority
```

**Expected Behavior:**
- Tries all skill fallbacks within XRAY before trying CT
- Path: XRAY[Herz→Notfall→Normal] → CT[Herz→Notfall→Normal] → MR[...]

**Test:**
```bash
curl http://localhost:5000/api/xray/herz
```

**Log Indicators:**
```
Assignment request: modality=xray, role=herz, strict=False
Selected worker: <name> using column Notfall (modality xray)
Fallback modality ct used for role herz (requested xray)
```

**What to verify:**
- [ ] Tries Herz in XRAY first
- [ ] Falls back to Notfall/Normal in XRAY before trying CT
- [ ] Only moves to CT if XRAY skills exhausted

---

### Strategy 2: `modality_priority`

**Configuration:**
```yaml
balancer:
  fallback_strategy: modality_priority
```

**Expected Behavior:**
- Tries Herz across all modalities before trying Notfall
- Path: Herz[XRAY→CT→MR] → Notfall[XRAY→CT→MR] → Normal[...]

**Test:**
```bash
# Restart Flask after config change
curl http://localhost:5000/api/xray/herz
```

**Log Indicators:**
```
Trying skill Herz across modalities ['xray', 'ct', 'mr']
Fallback used: skill=Herz, modality=ct (requested: skill=Herz, modality=xray)
```

**What to verify:**
- [ ] Tries Herz in XRAY, CT, MR before trying Notfall
- [ ] Log shows "Trying skill X across modalities"
- [ ] Prioritizes skill specialization over modality locality

---

### Strategy 3: `pool_priority` (NEW!)

**Configuration:**
```yaml
balancer:
  fallback_strategy: pool_priority
```

**Expected Behavior:**
- Evaluates ALL (skill, modality) combinations simultaneously
- Selects globally optimal worker based on load
- Ignores sequential fallback paths

**Test:**
```bash
# Restart Flask after config change
curl http://localhost:5000/api/xray/herz
```

**Log Indicators:**
```
Building candidate pool for role herz: skills=['Herz', 'Notfall', 'Normal'], modalities=['xray', 'ct', 'mr'] (pool_priority mode)
Selected from pool of 9 candidates: skill=Notfall, modality=ct, person=WorkerX, ratio=0.1234
```

**What to verify:**
- [ ] Log shows "Building candidate pool"
- [ ] Pool size shown (e.g., "pool of 9 candidates")
- [ ] May select any valid (skill, modality) combination
- [ ] Selection based on lowest `ratio` (weighted_count / hours_worked)

---

## 🔍 Advanced Testing Scenarios

### Scenario 1: Load Balancing Comparison

**Setup:**
1. Upload worker schedules with one heavily loaded worker
2. Test same request with all three strategies
3. Compare which worker gets assigned

**Expected:**
- `skill_priority`: May keep assigning same overloaded worker if they're in primary modality
- `modality_priority`: May still pick overloaded specialist
- `pool_priority`: **Should pick least loaded worker globally**

### Scenario 2: Strict Mode

**Test:**
```bash
# Request skill that doesn't exist in modality
curl http://localhost:5000/api/xray/herz/strict
```

**Expected:**
- Returns "Keine Person in dieser Gruppe verfügbar"
- No fallback to other skills or modalities
- Works same for all strategies (fallbacks disabled)

### Scenario 3: Cross-Modality Surge

**Setup:**
1. Configure: `xray: [[ct, mr]]` in modality_fallbacks
2. Make XRAY completely busy
3. Request XRAY worker

**Expected:**
- `skill_priority`: XRAY[all skills] → CT[all skills] → MR[all skills]
- `modality_priority`: Herz[XRAY→CT→MR] → Notfall[XRAY→CT→MR]
- `pool_priority`: Evaluates all 9 combinations, picks best

### Scenario 4: Imbalance Triggering

**Setup:**
1. Set `imbalance_threshold_pct: 30`
2. Assign workers until one has 30% more assignments
3. Make next request

**Expected:**
- System should trigger fallback even if primary skill available
- Log shows imbalance detection
- Works for all strategies

---

## 📊 Response Field Reference

| Field | Type | Description |
|-------|------|-------------|
| `Draw Time` | string | Time of assignment (HH:MM:SS) |
| `Assigned Person` | string | Worker name or error message |
| `modality_requested` | string | Modality in URL |
| `modality_used` | string | Actual modality worker came from |
| `skill_used` | string | Actual skill column used |
| `fallback_allowed` | boolean | Whether fallbacks were enabled |
| `strict_request` | boolean | Whether /strict endpoint was used |
| `Summe` | object | Per-worker assignment totals for this modality |
| `Global` | object | Per-worker cross-modality assignment counts |
| `Normal`, `Notfall`, etc. | object | Per-skill assignment counts |

---

## 🐛 Troubleshooting

### Issue: "No workers available"

**Possible causes:**
1. No workers scheduled at current time
2. All workers exhausted (check imbalance settings)
3. Strict mode used when skill doesn't exist

**Debug:**
```bash
# Check current time workers
curl http://localhost:5000/api/quick_reload?modality=ct | jq '.available_buttons'

# Check logs
tail -100 logs/selection.log | grep "No workers"
```

### Issue: Wrong strategy executing

**Symptoms:**
- Log doesn't show expected strategy messages
- Wrong fallback order

**Debug:**
1. Check config.yaml: `grep fallback_strategy config.yaml`
2. Restart Flask (config loaded at startup)
3. Check logs for dispatcher: `grep "strategy" logs/selection.log`

### Issue: Fallbacks not working

**Possible causes:**
1. `allow_fallback_on_imbalance: false` in config
2. `balancer.enabled: false`
3. Using /strict endpoint

**Debug:**
```bash
# Check balancer config
grep -A 10 "balancer:" config.yaml

# Test without strict
curl http://localhost:5000/api/ct/herz  # Should allow fallbacks
```

---

## ✅ Testing Checklist

Before deploying to production:

- [ ] All three strategies tested with real data
- [ ] Strict mode verified to block fallbacks
- [ ] Cross-modality fallbacks working
- [ ] Imbalance detection triggering correctly
- [ ] Logs showing correct strategy execution
- [ ] UI buttons reflect available workers
- [ ] Global counters updating correctly
- [ ] Weighted ratios calculating properly
- [ ] Daily reset functioning (if testing over midnight)
- [ ] Backup/restore working after assignments

---

## 📝 Expected Log Patterns

### skill_priority mode:
```
Assignment request: modality=xray, role=herz, strict=False, time=14:30:15
Selected worker: WorkerA using column Herz (modality xray)
```

### modality_priority mode:
```
Trying skill Herz across modalities ['xray', 'ct', 'mr']
Fallback used: skill=Herz, modality=ct (requested: skill=Herz, modality=xray)
Selected worker: WorkerB using column Herz (modality ct)
```

### pool_priority mode:
```
Building candidate pool for role herz: skills=['Herz', 'Notfall', 'Normal'], modalities=['xray', 'ct', 'mr'] (pool_priority mode)
Selected from pool of 9 candidates: skill=Notfall, modality=ct, person=WorkerC, ratio=0.1234
Fallback used: skill=Notfall, modality=ct (requested: skill=Herz, modality=xray)
```

---

## 🚀 Quick Start Testing

```bash
# 1. Start the app
flask --app app run --debug

# 2. Test basic functionality
curl http://localhost:5000/api/ct/normal

# 3. Test each strategy
# Edit config.yaml -> fallback_strategy: skill_priority
# Restart Flask
curl http://localhost:5000/api/xray/herz

# Edit config.yaml -> fallback_strategy: modality_priority
# Restart Flask
curl http://localhost:5000/api/xray/herz

# Edit config.yaml -> fallback_strategy: pool_priority
# Restart Flask
curl http://localhost:5000/api/xray/herz

# 4. Compare logs
tail -100 logs/selection.log
```

---

## 🎯 Success Criteria

The implementation is ready for production when:

1. ✅ All three strategies execute without errors
2. ✅ Strategy behavior matches documentation
3. ✅ Fallback chains follow configured paths
4. ✅ Load balancing prevents worker overload
5. ✅ Strict mode correctly blocks fallbacks
6. ✅ Logs clearly show strategy execution
7. ✅ API responses include fallback information
8. ✅ Cross-modality borrowing works as expected
9. ✅ Global counters track correctly
10. ✅ UI reflects real-time availability

---

**All systems GREEN and ready for testing! 🎉**
