function toggleDisplayOrder() {
  displayOrder = displayOrder === 'modality-first' ? 'skill-first' : 'modality-first';
  const newText = displayOrder === 'modality-first' ? 'Mod → Skill' : 'Skill → Mod';
  const newTitle = displayOrder === 'modality-first'
    ? 'Current: Modalities as groups, skills as sub-columns. Click to switch.'
    : 'Current: Skills as groups, modalities as sub-columns. Click to switch.';
  // Update both buttons (today and tomorrow tabs)
  ['display-order-toggle-today', 'display-order-toggle-tomorrow'].forEach(id => {
    const btn = document.getElementById(id);
    if (btn) {
      btn.textContent = newText;
      btn.title = newTitle;
    }
  });
  renderTable('today');
  renderTable('tomorrow');
}

function updateTableFilter(tab) {
  const hideZero = document.getElementById(`filter-hide-zero-${tab}`)?.checked || false;
  if (!tableFilters[tab]) {
    tableFilters[tab] = { modality: '', skill: '', hideZero };
  } else {
    tableFilters[tab].hideZero = hideZero;
  }
  renderTable(tab);

  // Also apply filters to the timeline
  applyTimelineFilters(tab);
}

// Helper: Apply current filters to the timeline
function applyTimelineFilters(tab) {
  const gridEl = document.getElementById(`timeline-grid-${tab}`);
  if (!gridEl || typeof TimelineChart === 'undefined') return;

  const filter = tableFilters[tab] || {};
  // Convert skill name to slug for timeline filtering
  const skillSlug = filter.skill ? (SKILL_SETTINGS[filter.skill]?.slug || filter.skill.toLowerCase().replace(/[^a-z0-9-]/g, '-')) : '';

  TimelineChart.applyFilters(gridEl, {
    skill: skillSlug,
    modality: filter.modality || '',
    hideZero: filter.hideZero || false
  });
}

function filterByModality(tab, modality) {
  // Update button states
  const buttons = document.querySelectorAll(`[data-modality]`);
  buttons.forEach(btn => {
    if (btn.closest('.filter-bar') && btn.onclick && btn.onclick.toString().includes(`'${tab}'`)) {
      btn.classList.toggle('active', btn.getAttribute('data-modality') === modality);
    }
  });

  // Update filter and render
  const hideZero = document.getElementById(`filter-hide-zero-${tab}`)?.checked || false;
  tableFilters[tab] = {
    modality: modality.toLowerCase(),
    skill: tableFilters[tab]?.skill || '',
    hideZero
  };
  renderTable(tab);

  // Apply combined filters to the timeline (respects skill + modality + hideZero)
  applyTimelineFilters(tab);
}

function filterBySkill(tab, skill) {
  // Update button states
  const buttons = document.querySelectorAll(`[data-skill]`);
  buttons.forEach(btn => {
    if (btn.closest('.filter-bar') && btn.onclick && btn.onclick.toString().includes(`'${tab}'`)) {
      btn.classList.toggle('active', btn.getAttribute('data-skill') === skill);
    }
  });

  // Update filter and render
  const hideZero = document.getElementById(`filter-hide-zero-${tab}`)?.checked || false;
  tableFilters[tab] = {
    modality: tableFilters[tab]?.modality || '',
    skill: skill,
    hideZero
  };
  renderTable(tab);

  // Apply combined filters to the timeline (respects skill + modality + hideZero)
  applyTimelineFilters(tab);
}

function parseDayTimes(dayTimes) {
  if (typeof dayTimes !== 'string') return null;
  const parts = dayTimes.split('-').map(part => part.trim());
  if (parts.length !== 2) return null;
  const [startTime, endTime] = parts;
  if (!startTime || !endTime) return null;
  return [startTime, endTime];
}

function getGapTimeRange(taskConfig, targetDay) {
  if (!taskConfig) return null;
  const segments = Array.isArray(taskConfig.segments) ? taskConfig.segments : [];
  if (segments.length > 0) {
    for (const segment of segments) {
      const segmentTimes = segment?.times || {};
      const resolvedSegmentTimes = typeof resolveDayTimes === 'function'
        ? resolveDayTimes(segmentTimes, targetDay)
        : (segmentTimes[targetDay] || segmentTimes.default);
      const segmentRanges = normalizeTaskTimeRanges(resolvedSegmentTimes);
      if (segmentRanges.length > 0) {
        return parseDayTimes(segmentRanges[0]);
      }
    }
  }
  const times = taskConfig.times || {};
  const dayTimes = typeof resolveDayTimes === 'function'
    ? resolveDayTimes(times, targetDay)
    : (times[targetDay] || times.default);
  if (Array.isArray(dayTimes)) {
    return parseDayTimes(dayTimes[0]);
  }
  return parseDayTimes(dayTimes);
}

function syncSkillValueControlClass(el, value = null) {
  if (!el) return;
  const borderClasses = ['skill-border--1', 'skill-border-0', 'skill-border-w', 'skill-border-1'];
  el.classList.remove(...borderClasses);
  const resolvedValue = value === null ? el.value : value;
  const borderClass = getSkillBorderClass(resolvedValue);
  if (borderClass) {
    el.classList.add(borderClass);
  }
  el.dataset.skillValue = displaySkillValue(normalizeSkillValueJS(resolvedValue));
}

// Toggle inline edit mode
async function toggleEditMode(tab) {
  const wasActive = editMode[tab];
  editMode[tab] = !editMode[tab];
  pendingChanges[tab] = {};  // Reset pending changes
  applyEditModeUI(tab);
  if (tab === 'today' && document.getElementById('auto-refresh-today')?.checked) {
    updatePrepRefreshStatus(tab, editMode[tab] ? 'Paused during edits' : 'Auto-refresh on');
  }
  if (wasActive && !editMode[tab]) {
    await loadData();
    return;
  }
  renderTable(tab);
}

// Track inline skill change (supports adding new modalities with rowIndex=-1)
function onInlineSkillChange(tab, modKey, rowIndex, skill, value, groupIdx, shiftIdx, el = null) {
  const normalizedVal = normalizeSkillValueJS(value);

  // Handle new modality additions (rowIndex = -1)
  if (rowIndex === -1) {
    const key = `new-${groupIdx}-${shiftIdx}-${modKey}`;
    if (!pendingChanges[tab][key]) {
      pendingChanges[tab][key] = { modality: modKey, row_index: -1, groupIdx, shiftIdx, isNew: true, materialize: true, updates: {} };
    }
    pendingChanges[tab][key].updates[skill] = normalizedVal;
    if (isWeightedSkill(normalizedVal)) {
      const currentWeight = el?.nextElementSibling ? parseFloat(el.nextElementSibling.value || '1.0') : 1.0;
      pendingChanges[tab][key].updates['Modifier'] = currentWeight;
    } else {
      delete pendingChanges[tab][key].updates['Modifier'];
    }
  } else {
    const key = `${modKey}-${rowIndex}`;
    if (!pendingChanges[tab][key]) {
      pendingChanges[tab][key] = { modality: modKey, row_index: rowIndex, updates: {} };
    }
    pendingChanges[tab][key].updates[skill] = normalizedVal;
    if (isWeightedSkill(normalizedVal)) {
      const currentWeight = el?.nextElementSibling ? parseFloat(el.nextElementSibling.value || '1.0') : 1.0;
      pendingChanges[tab][key].updates['Modifier'] = currentWeight;
    } else {
      delete pendingChanges[tab][key].updates['Modifier'];
    }
  }

  if (el && el.nextElementSibling) {
    el.nextElementSibling.style.display = isWeightedSkill(normalizedVal) ? '' : 'none';
  }

  updateSaveButtonCount(tab);
}

// Track inline modifier change per modality
function onInlineModifierChange(tab, modKey, rowIndex, value, groupIdx, shiftIdx) {
  const parsed = parseFloat(value) || 1.0;

  if (rowIndex === -1) {
    // New modality addition
    const key = `new-${groupIdx}-${shiftIdx}-${modKey}`;
    if (!pendingChanges[tab][key]) {
      pendingChanges[tab][key] = { modality: modKey, row_index: -1, groupIdx, shiftIdx, isNew: true, materialize: true, updates: {} };
    }
    pendingChanges[tab][key].updates['Modifier'] = parsed;
  } else {
    const key = `${modKey}-${rowIndex}`;
    if (!pendingChanges[tab][key]) {
      pendingChanges[tab][key] = { modality: modKey, row_index: rowIndex, updates: {} };
    }
    pendingChanges[tab][key].updates['Modifier'] = parsed;
  }

  updateSaveButtonCount(tab);
}

// Valid skill values for quick edit validation
const VALID_SKILL_VALUES = ['-1', '0', '1', 'w', 'W'];
const VALID_MODIFIER_VALUES = [0.3, 0.5, 0.75, 0.9, 1, 1.0, 1.1, 1.2, 1.25];

// Validate and save skill input on blur
function validateAndSaveSkill(el) {
  const raw = (el.value || '').trim().toLowerCase();
  let normalized;

  // Validate input - only allow -1, 0, 1, w
  if (raw === '-1' || raw === '-') normalized = -1;
  else if (raw === '0' || raw === '') normalized = 0;
  else if (raw === '1') normalized = 1;
  else if (raw === 'w' || raw === '2') normalized = 'w';
  else {
    // Invalid - reset to 0
    normalized = 0;
    showMessage('error', 'Valid values: -1, 0, 1, w');
  }

  // Update display
  el.value = displaySkillValue(normalized);
  syncSkillValueControlClass(el, normalized);

  // Trigger change tracking
  const { tab, mod, row, skill, gidx, sidx } = el.dataset;
  onInlineSkillChange(tab, mod, parseInt(row, 10), skill, normalized, parseInt(gidx, 10), parseInt(sidx, 10), el);
}

// Handle keyboard shortcuts for skill input
function handleSkillKeydown(event, el) {
  if (event.key === 'Enter') {
    el.blur();
    event.preventDefault();
  } else if (event.key === 'Tab') {
    // Allow normal tab behavior
  } else if (event.key === 'ArrowUp') {
    // Cycle up (towards 1): -1 -> w -> 0 -> 1 -> -1
    // Order: 1, 0, w, -1
    const val = normalizeSkillValueJS(el.value);
    let next;
    if (val === -1) next = 'w';
    else if (isWeightedSkill(val)) next = 0;
    else if (val === 0) next = 1;
    else next = -1;
    el.value = displaySkillValue(next);
    validateAndSaveSkill(el);
    event.preventDefault();
  } else if (event.key === 'ArrowDown') {
    // Cycle down (towards -1): 1 -> 0 -> w -> -1 -> 1
    // Order: 1, 0, w, -1
    const val = normalizeSkillValueJS(el.value);
    let next;
    if (val === 1) next = 0;
    else if (val === 0) next = 'w';
    else if (isWeightedSkill(val)) next = -1;
    else next = 1;
    el.value = displaySkillValue(next);
    validateAndSaveSkill(el);
    event.preventDefault();
  }
}

// Validate and save modifier input on blur (per-modality)
function validateAndSaveModifier(el) {
  let parsed = parseFloat(el.value);

  // Validate - clamp to valid range
  if (isNaN(parsed) || parsed < 0.3) parsed = 0.3;
  else if (parsed > 3.0) parsed = 3.0;

  // Round to nearest valid value
  const validValues = [0.3, 0.5, 0.75, 0.9, 1.0, 1.1, 1.2, 1.25, 1.5, 1.75, 2.0, 2.5, 3.0];
  parsed = validValues.reduce((prev, curr) =>
    Math.abs(curr - parsed) < Math.abs(prev - parsed) ? curr : prev
  );

  el.value = parsed;

  // Trigger change tracking
  const { tab, mod, row, gidx, sidx } = el.dataset;
  onInlineModifierChange(tab, mod, parseInt(row, 10), parsed, parseInt(gidx, 10), parseInt(sidx, 10));
}

// Validate and save shift-level modifier (applies to all modalities in the shift)
function validateAndSaveShiftModifier(el) {
  let parsed = parseFloat(el.value);

  // Validate - clamp to valid range
  if (isNaN(parsed) || parsed < 0.3) parsed = 0.3;
  else if (parsed > 3.0) parsed = 3.0;

  // Round to nearest valid value
  const validValues = [0.3, 0.5, 0.75, 0.9, 1.0, 1.1, 1.2, 1.25, 1.5, 1.75, 2.0, 2.5, 3.0];
  parsed = validValues.reduce((prev, curr) =>
    Math.abs(curr - parsed) < Math.abs(prev - parsed) ? curr : prev
  );

  el.value = parsed;

  // Trigger change tracking for ALL modalities in this shift
  const { tab, gidx, sidx } = el.dataset;
  onInlineShiftModifierChange(tab, parseInt(gidx, 10), parseInt(sidx, 10), parsed);

  updateSaveButtonCount(tab);
}

// Handle keyboard for modifier input
function handleModKeydown(event, el) {
  // Determine if this is shift-level (no mod attribute) or modality-level modifier
  const isShiftLevel = !el.dataset.mod;
  const saveFunction = isShiftLevel ? validateAndSaveShiftModifier : validateAndSaveModifier;

  if (event.key === 'Enter') {
    el.blur();
    event.preventDefault();
  } else if (event.key === 'ArrowUp') {
    const val = parseFloat(el.value) || 1.0;
    const validValues = [0.3, 0.5, 0.75, 0.9, 1.0, 1.1, 1.2, 1.25, 1.5, 1.75, 2.0, 2.5, 3.0];
    const idx = validValues.indexOf(val);
    const next = idx < validValues.length - 1 ? validValues[idx + 1] : validValues[validValues.length - 1];
    el.value = next;
    saveFunction(el);
    event.preventDefault();
  } else if (event.key === 'ArrowDown') {
    const val = parseFloat(el.value) || 1.0;
    const validValues = [0.3, 0.5, 0.75, 0.9, 1.0, 1.1, 1.2, 1.25, 1.5, 1.75, 2.0, 2.5, 3.0];
    const idx = validValues.indexOf(val);
    const next = idx > 0 ? validValues[idx - 1] : validValues[0];
    el.value = next;
    saveFunction(el);
    event.preventDefault();
  }
}

// Save all inline changes (handles both updates and new modality additions)
async function saveInlineChanges(tab) {
  const changeEntries = Object.entries(pendingChanges[tab] || {});
  if (changeEntries.length === 0) {
    updateSaveInlineStatus(tab, 'No changes to save', 'error');
    return;
  }
  const updateEndpoint = tab === 'today' ? '/api/live-schedule/update-row' : '/api/prep-next-day/update-row';
  const addEndpoint = tab === 'today' ? '/api/live-schedule/add-worker' : '/api/prep-next-day/add-worker';
  const deleteEndpoint = tab === 'today' ? '/api/live-schedule/delete-worker' : '/api/prep-next-day/delete-worker';

  // Collect errors instead of throwing on first failure
  const errors = [];
  let successCount = 0;
  const succeededKeys = new Set();

  for (const [changeKey, change] of changeEntries) {
    const changeUnits = getPendingChangeUnits(change);
    try {
      if (change.isDelete) {
        await postJsonWithSnapshot(tab, deleteEndpoint, {
          modality: change.modality,
          row_index: change.row_index,
          verify_ppl: change.verify_ppl
        }, {
          conflictMessage: 'Schedule changed in the background. Latest version was reloaded. Review pending edits and save again.',
        });
        successCount += changeUnits;
        succeededKeys.add(changeKey);
      } else if (change.isNew) {
        // New modality addition - need to add via add-worker endpoint
        const group = entriesData[tab][change.groupIdx];
        const shift = group ? getTableShifts(group)[change.shiftIdx] : null;
        if (!group || !shift) continue;

        // Build worker_data for the new modality
        const workerData = {
          PPL: group.worker,
          start_time: shift.start_time,
          end_time: shift.end_time,
          Modifier: change.updates.Modifier || 1.0,
          tasks: shift.task || '',
          row_type: shift.is_gap_entry ? 'gap' : 'shift',
          counts_for_hours: shift.counts_for_hours !== false,
          training: shift.training !== false,
          materialize: true
        };
        // Get original skill values from the placeholder modality
        const originalSkills = shift.modalities[change.modality]?.skills || {};
        // Add all skills (preserve original values for unchanged skills)
        SKILLS.forEach(skill => {
          if (change.updates[skill] !== undefined) {
            workerData[skill] = change.updates[skill];
          } else {
            workerData[skill] = originalSkills[skill] !== undefined ? originalSkills[skill] : -1;
          }
        });

        await postJsonWithSnapshot(tab, addEndpoint, {
          modality: change.modality,
          worker_data: workerData
        }, {
          conflictMessage: 'Schedule changed in the background. Latest version was reloaded. Review pending edits and save again.',
        });
        successCount += changeUnits;
        succeededKeys.add(changeKey);
      } else {
        // Existing entry update
        await postJsonWithSnapshot(tab, updateEndpoint, change, {
          conflictMessage: 'Schedule changed in the background. Latest version was reloaded. Review pending edits and save again.',
        });
        successCount += changeUnits;
        succeededKeys.add(changeKey);
      }
    } catch (fetchError) {
      errors.push(fetchError.message || 'Unknown error');
      if (fetchError.isConflict) {
        break;
      }
    }
  }

  // Show appropriate message based on results
  if (errors.length === 0) {
    updateSaveInlineStatus(tab, `Saved ${successCount} change${successCount !== 1 ? 's' : ''}`, 'success');
  } else if (successCount > 0) {
    updateSaveInlineStatus(tab, `Saved ${successCount}, failed ${errors.length}: ${errors[0]}`, 'error');
  } else {
    updateSaveInlineStatus(tab, `All ${errors.length} changes failed: ${errors[0]}`, 'error');
  }

  succeededKeys.forEach(key => {
    delete pendingChanges[tab][key];
  });
  applyEditModeUI(tab);
  if (errors.length === 0) {
    await loadData();
  }
}

// Update hours toggle label based on checkbox state
function updateHoursToggleLabel(checkbox) {
  const label = checkbox.nextElementSibling;
  if (label && label.classList.contains('hours-toggle-label')) {
    if (checkbox.checked) {
      label.textContent = 'Counts';
      label.classList.remove('no-count');
      label.classList.add('counts');
    } else {
      label.textContent = 'No count';
      label.classList.remove('counts');
      label.classList.add('no-count');
    }
  }
}

function updateTrainingToggleLabel(checkbox) {
  const label = checkbox.nextElementSibling;
  if (label && label.dataset?.role === 'training-label') {
    if (checkbox.checked) {
      label.textContent = 'Training on';
      label.classList.remove('no-count');
      label.classList.add('counts');
    } else {
      label.textContent = 'Training off';
      label.classList.remove('counts');
      label.classList.add('no-count');
    }
  }
}

function isTabAvailable(tab) {
  return Boolean(document.getElementById(`content-${tab}`));
}

function updatePrepLoadedLabel(text) {
  const loadedEl = document.getElementById('prep-data-loaded-label');
  if (loadedEl) {
    loadedEl.textContent = text || '';
  }
}

function updatePrepLastEditLabel(text) {
  const editEl = document.getElementById('prep-last-edit-label');
  if (editEl) {
    editEl.textContent = text || '';
  }
}

function updatePrepLoadResultLabel(text, kind = 'info', mode = 'tomorrow') {
  const statusEl = document.getElementById(mode === 'today' ? 'load-status-today' : 'load-status-tomorrow');
  if (!statusEl) return;

  statusEl.textContent = text || '';
  statusEl.style.color = kind === 'error' ? '#dc3545' : kind === 'success' ? '#28a745' : '';
}

function setSnapshotVersion(tab, value) {
  snapshotVersions[tab] = value || null;
}

function getSnapshotVersion(tab) {
  return snapshotVersions[tab] || null;
}

function buildMutationPayload(tab, payload, options = {}) {
  const {
    includeSnapshotVersion = true,
  } = options;
  const requestPayload = {
    ...payload,
  };
  if (includeSnapshotVersion) {
    requestPayload.snapshot_version = getSnapshotVersion(tab);
  }
  if (tab === 'tomorrow' && prepTargetDate) {
    requestPayload.target_date = prepTargetDate;
  }
  return requestPayload;
}

function updateSnapshotVersionFromResponse(tab, result) {
  if (result && result.snapshot_version) {
    setSnapshotVersion(tab, result.snapshot_version);
  }
}

function markDraftModalityMaterialized(shiftIdx, modKey) {
  if (!editPlanDraft || !editPlanDraft.shifts) return;
  const shift = editPlanDraft.shifts[shiftIdx];
  const modData = shift?.modalities?.[modKey];
  if (modData) {
    modData.materialize = true;
  }
}

function markDraftShiftMaterialized(shiftIdx) {
  if (!editPlanDraft || !editPlanDraft.shifts) return;
  const shift = editPlanDraft.shifts[shiftIdx];
  Object.values(shift?.modalities || {}).forEach(modData => {
    if (modData) {
      modData.materialize = true;
    }
  });
}

const saveStatusTimers = { today: null, tomorrow: null };

function updateSaveInlineStatus(tab, message, kind = 'info') {
  const statusEl = document.getElementById(`save-status-${tab}`);
  if (!statusEl) return;

  if (saveStatusTimers[tab]) {
    clearTimeout(saveStatusTimers[tab]);
    saveStatusTimers[tab] = null;
  }

  if (!message) {
    statusEl.textContent = '';
    statusEl.className = 'prep-inline-save-status';
    return;
  }

  statusEl.textContent = message;
  statusEl.className = `prep-inline-save-status ${kind === 'success' ? 'is-success' : kind === 'error' ? 'is-error' : 'is-info'}`;

  if (kind !== 'info') {
    saveStatusTimers[tab] = setTimeout(() => {
      const currentEl = document.getElementById(`save-status-${tab}`);
      if (currentEl && currentEl.textContent === message) {
        currentEl.textContent = '';
        currentEl.className = 'prep-inline-save-status';
      }
      saveStatusTimers[tab] = null;
    }, 5000);
  }
}

function getSnapshotConflictMessage(result) {
  return result?.error || 'Schedule changed in the background. Latest version was reloaded. Please review your edit.';
}

async function postJsonWithSnapshot(tab, endpoint, payload, options = {}) {
  const {
    reloadOnConflict = false,
    conflictMessage = null,
    includeSnapshotVersion = true,
  } = options;

  const response = await fetch(endpoint, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(buildMutationPayload(tab, payload, { includeSnapshotVersion })),
  });

  const result = await response.json().catch(() => ({}));
  updateSnapshotVersionFromResponse(tab, result);

  if (response.status === 409) {
    const message = conflictMessage || getSnapshotConflictMessage(result);
    updateSaveInlineStatus(tab, message, 'error');
    if (reloadOnConflict) {
      await loadData();
    }
    const error = new Error(message);
    error.isConflict = true;
    error.result = result;
    throw error;
  }

  if (!response.ok) {
    throw new Error(result.error || 'Request failed');
  }

  return result;
}

function updatePrepSelectionControls() {
  const locked = Boolean(editMode.tomorrow);
  const lockMessage = locked
    ? 'Exit Quick Edit before changing or reloading the selected date.'
    : 'Select a date to load staged tomorrow data.';

  const inputEl = document.getElementById('prep-target-date');
  if (inputEl) {
    inputEl.disabled = locked;
    inputEl.title = lockMessage;
  }

  document.querySelectorAll('[data-prep-date-step]').forEach(btn => {
    btn.disabled = locked;
    btn.title = lockMessage;
  });

  const reloadBtn = document.querySelector('.reload-selected-date-btn');
  if (reloadBtn) {
    reloadBtn.disabled = locked;
    reloadBtn.title = lockMessage;
  }
}

function formatPrepLoadedLabel(weekdayName, targetDate) {
  if (weekdayName && targetDate) {
    const dateObj = new Date(`${targetDate}T00:00:00`);
    if (!Number.isNaN(dateObj.getTime())) {
      return `${weekdayName} (${dateObj.toLocaleDateString('de-DE')})`;
    }
  }
  return targetDate || weekdayName || '';
}

function updatePrepTargetUI() {
  const labelEl = document.getElementById('prep-data-loaded-label');
  if (labelEl && prepTargetWeekday && prepTargetDateGerman) {
    labelEl.textContent = `${prepTargetWeekday} (${prepTargetDateGerman})`;
  }
  const inputEl = document.getElementById('prep-target-date');
  if (inputEl) {
    if (prepMinDate) {
      inputEl.min = prepMinDate;
    }
    if (prepTargetDate) {
      inputEl.value = prepTargetDate;
    }
  }
  updatePrepSelectionControls();
}

function shiftPrepDate(offsetDays) {
  if (editMode.tomorrow) {
    showMessage('error', 'Exit Quick Edit before changing the selected date.');
    updatePrepSelectionControls();
    return;
  }

  const inputEl = document.getElementById('prep-target-date');
  if (!inputEl || !inputEl.value) return;

  const currentDate = new Date(`${inputEl.value}T00:00:00`);
  if (Number.isNaN(currentDate.getTime())) return;

  currentDate.setDate(currentDate.getDate() + offsetDays);
  const yyyy = currentDate.getFullYear();
  const mm = String(currentDate.getMonth() + 1).padStart(2, '0');
  const dd = String(currentDate.getDate()).padStart(2, '0');
  const nextValue = `${yyyy}-${mm}-${dd}`;

  if (prepMinDate && nextValue < prepMinDate) {
    showMessage('error', `Prep-Datum muss ab ${prepMinDate} liegen.`);
    return;
  }

  inputEl.value = nextValue;
  onPrepDateInputChange();
}

function onPrepDateInputChange() {
  const inputEl = document.getElementById('prep-target-date');
  if (!inputEl) return;
  if (editMode.tomorrow) {
    showMessage('error', 'Exit Quick Edit before changing the selected date.');
    updatePrepSelectionControls();
    inputEl.value = prepTargetDate || inputEl.value;
    return;
  }
  const value = inputEl.value;
  if (!value) return;
  const previousDate = prepTargetDate;
  if (prepMinDate && value < prepMinDate) {
    showMessage('error', `Prep-Datum muss ab ${prepMinDate} liegen.`);
    inputEl.value = prepMinDate;
    setPrepTargetMeta({ dateValue: prepMinDate });
    updatePrepTargetUI();
    return;
  }
  setPrepTargetMeta({ dateValue: value });
  updatePrepTargetUI();
  const hasPendingChanges = Object.keys(pendingChanges.tomorrow || {}).length > 0;
  if (hasPendingChanges) {
    const message = `Changing the selected date will overwrite unsaved Quick Edit changes and reload the staged tomorrow data for ${value}. Continue?`;
    if (!window.confirm(message)) {
      setPrepTargetMeta({ dateValue: previousDate });
      updatePrepTargetUI();
      return;
    }
  }
  loadFromCSV('next', { confirm: false, forceCsv: false });
}

// Load data for a specific tab (lazy loading)
async function loadTabData(tab) {
  if (!isTabAvailable(tab)) {
    return;
  }
  const requestId = ++loadRequestId[tab];
  const hadLoadedData = Boolean(dataLoaded[tab]);
  try {
    const endpoint = tab === 'today'
      ? '/api/live-schedule/data'
      : `/api/prep-next-day/data${prepTargetDate ? `?target_date=${encodeURIComponent(prepTargetDate)}` : ''}`;
    const response = await fetch(endpoint);

    if (requestId !== loadRequestId[tab]) {
      return;
    }
    if (!response.ok) {
      const text = await response.text();
      console.error(`${tab} API error:`, text);
      if (requestId === loadRequestId[tab] && !hadLoadedData) {
        rawData[tab] = {};
        dataLoaded[tab] = false;
      }
      return;
    }

    const contentType = response.headers.get('content-type');
    let respData;
    if (contentType && contentType.includes('application/json')) {
      respData = await response.json();
      if (requestId !== loadRequestId[tab]) {
        return;
      }
      rawData[tab] = respData.modalities || respData;
    } else {
      console.error(`${tab} API returned non-JSON`);
      if (requestId === loadRequestId[tab] && !hadLoadedData) {
        rawData[tab] = {};
        dataLoaded[tab] = false;
      }
      return;
    }

    if (requestId !== loadRequestId[tab]) {
      return;
    }
    workerRevisions[tab] = respData.worker_revisions || {};
    const result = buildEntriesByWorker(respData.modalities || respData, tab);
    entriesData[tab] = result.entries;
    workerCounts[tab] = result.counts;
    dataLoaded[tab] = true;
    setSnapshotVersion(tab, respData.snapshot_version || null);

    if (tab === 'tomorrow') {
    if (respData.target_date || respData.target_weekday_name) {
      setPrepTargetMeta({
        dateValue: respData.target_date,
        weekdayName: respData.target_weekday_name,
      });
      updatePrepTargetUI();
      }
      updatePrepLoadedLabel(respData.prep_loaded_label || formatPrepLoadedLabel(respData.target_weekday_name, respData.target_date));
      updatePrepLastEditLabel(respData.prep_last_edit_label || respData.last_modified || respData.last_prepped_at || '');
      if (respData.prep_load_source === 'snapshot') {
        updatePrepLoadResultLabel('');
      }
    }

    renderTable(tab);
    renderTimeline(tab);  // Update timeline chart
    applyTimelineFilters(tab);  // Apply current filters to timeline
  } catch (error) {
    console.error(`Load error for ${tab}:`, error);
    if (requestId === loadRequestId[tab]) {
      showMessage('error', `Error loading ${tab} data: ${error.message}`);
      dataLoaded[tab] = false;
    }
  }
}

// Load data for both tabs (used after mutations)
async function loadData() {
  // Reset loaded flags to force refresh
  dataLoaded.today = false;
  dataLoaded.tomorrow = false;

  // Load current tab first (visible to user)
  await loadTabData(currentTab);

  // Load other tab in background
  const otherTab = currentTab === 'today' ? 'tomorrow' : 'today';
  if (isTabAvailable(otherTab)) {
    loadTabData(otherTab);
  }
}

function updatePrepRefreshStatus(tab, message) {
  const statusEl = document.getElementById(`prep-refresh-status-${tab}`);
  if (statusEl) {
    statusEl.textContent = message || '';
  }
}

function shouldAutoRefreshPrepTab(tab) {
  if (editMode[tab]) return false;
  if (Object.keys(pendingChanges[tab] || {}).length > 0) return false;
  if (document.getElementById('edit-modal')?.classList.contains('show')) return false;
  if (document.getElementById('break-popup')?.classList.contains('show')) return false;
  return true;
}

async function refreshPrepTab(tab, options = {}) {
  const silent = options.silent === true;
  if (!isTabAvailable(tab)) return;
  if (!shouldAutoRefreshPrepTab(tab)) {
    updatePrepRefreshStatus(tab, 'Paused during edits');
    return;
  }
  await loadTabData(tab);
  if (!silent) {
    updatePrepRefreshStatus(tab, `Updated ${new Date().toLocaleTimeString()}`);
  }
}

function togglePrepAutoRefresh(tab) {
  const checkbox = document.getElementById(`auto-refresh-${tab}`);
  if (prepAutoRefreshInterval[tab]) {
    clearInterval(prepAutoRefreshInterval[tab]);
    prepAutoRefreshInterval[tab] = null;
  }
  if (!checkbox?.checked) {
    updatePrepRefreshStatus(tab, 'Auto-refresh off');
    return;
  }
  updatePrepRefreshStatus(tab, 'Auto-refresh on');
  prepAutoRefreshInterval[tab] = setInterval(function() {
    refreshPrepTab(tab, { silent: true });
  }, 30000);
}

// Build grouped entries list: worker -> shifts (time-based) -> modality×skills matrix
function buildEntriesByWorker(data, tab = 'today') {
  const result = TimelineFeed.buildEntriesByWorker(data, {
    modalities: MODALITIES,
    skills: SKILLS,
    workerSkills: WORKER_SKILLS,
    taskRoles: TASK_ROLES,
    targetDay: getTargetWeekdayName(tab),
    normalizeSkillValue: normalizeSkillValueJS,
    lastAddedShiftMeta
  });
  result.entries = (result.entries || []).map(group => ({
    ...group,
    worker_revision: getWorkerRevision(tab, group.worker),
  }));
  if (lastAddedShiftMeta) {
    lastAddedShiftMeta = null;
  }
  return result;
}

// Track inline time change
function onInlineTimeChange(tab, groupIdx, shiftIdx, field, value) {
  const group = entriesData[tab][groupIdx];
  if (!group) return;
  const shift = getTableShifts(group)[shiftIdx];
  if (!shift) return;

  if (field === 'start') {
    shift.start_time = value;
  } else {
    shift.end_time = value;
  }

  // Update all modalities in this shift with new time
  Object.keys(shift.modalities).forEach(modKey => {
    const modData = shift.modalities[modKey];
    if (modData.row_index === undefined || modData.row_index < 0) return;
    const key = `${modKey}-${modData.row_index}`;
    if (!pendingChanges[tab][key]) {
      pendingChanges[tab][key] = { modality: modKey, row_index: modData.row_index, updates: {} };
    }
    pendingChanges[tab][key].updates[field === 'start' ? 'start_time' : 'end_time'] = value;
  });
  updateSaveButtonCount(tab);
}

// Track inline modifier change for the whole shift (one modifier)
function onInlineShiftModifierChange(tab, groupIdx, shiftIdx, value) {
  const group = entriesData[tab][groupIdx];
  if (!group) return;
  const shift = getTableShifts(group)[shiftIdx];
  if (!shift) return;

  const parsed = parseFloat(value);
  shift.modifier = parsed;

  Object.entries(shift.modalities).forEach(([modKey, modData]) => {
    if (modData.row_index === undefined || modData.row_index < 0) return;
    const key = `${modKey}-${modData.row_index}`;
    if (!pendingChanges[tab][key]) {
      pendingChanges[tab][key] = { modality: modKey, row_index: modData.row_index, updates: {} };
    }
    pendingChanges[tab][key].updates['Modifier'] = parsed;
  });
}

// Delete all entries for a worker
async function deleteWorkerEntries(tab, groupIdx) {
  const group = entriesData[tab][groupIdx];
  if (!group) return;

  const allEntries = group.allEntries || [];
  const workerLabel = getWorkerDisplayName(group.worker);
  if (!confirm(`Delete all ${allEntries.length} entries for ${workerLabel}?`)) return;

  const endpoint = tab === 'today' ? '/api/live-schedule/delete-worker' : '/api/prep-next-day/delete-worker';

  try {
    // Delete all entries in reverse order (to avoid index shifting issues)
    // Sort by row_index descending to delete from end first
    const sortedEntries = [...allEntries].sort((a, b) => b.row_index - a.row_index);
    for (const entry of sortedEntries) {
      await postJsonWithSnapshot(tab, endpoint, {
        modality: entry.modality,
        row_index: entry.row_index,
        verify_ppl: entry.worker,
      }, {
        reloadOnConflict: true,
      });
    }
    showMessage('success', `Deleted all entries for ${workerLabel}`);
    await loadData();
  } catch (error) {
    if (error.isConflict) {
      return;
    }
    showMessage('error', error.message);
  }
}

// Delete single entry
async function deleteEntry(tab, groupIdx, entryIdx) {
  const group = entriesData[tab][groupIdx];
  if (!group) return;
  const entry = group.entries[entryIdx];
  if (!entry) return;

  const workerLabel = getWorkerDisplayName(entry.worker);
  if (!confirm(`Delete entry for ${workerLabel} (${entry.modality.toUpperCase()} ${entry.start_time}-${entry.end_time})?`)) return;

  const endpoint = tab === 'today' ? '/api/live-schedule/delete-worker' : '/api/prep-next-day/delete-worker';

  try {
    await postJsonWithSnapshot(tab, endpoint, {
      modality: entry.modality,
      row_index: entry.row_index,
      verify_ppl: entry.worker,
    }, {
      reloadOnConflict: true,
    });
    showMessage('success', `Deleted entry for ${workerLabel}`);
    await loadData();
  } catch (error) {
    if (error.isConflict) {
      return;
    }
    showMessage('error', error.message);
  }
}

// Open Edit modal for a worker - edit skills per modality
function openEditModal(tab, groupIdx) {
  const group = entriesData[tab][groupIdx];
  if (!group) return;

  currentEditEntry = {
    tab,
    groupIdx,
    worker: group.worker,
    openedWorkerRevision: group.worker_revision || getWorkerRevision(tab, group.worker),
  };
  setEditPlanDraftFromGroup(group, { force: true });
  setModalMode('edit-plan');
  renderEditModalContent();
  document.getElementById('edit-modal').classList.add('show');
}

// Handle task change in existing shift (edit modal draft only)
function getTaskConfigByName(taskName) {
  return taskName ? resolveTaskConfigByName(taskName) : null;
}

function getTaskPersistedName(taskName) {
  const taskConfig = getTaskConfigByName(taskName);
  return taskConfig?.persisted_name || taskConfig?.name || taskName;
}

function buildGapPreviewFromTaskConfig(taskName, taskConfig, targetDay) {
  const [startTime, endTime] = getGapTimeRange(taskConfig, targetDay) || ['12:00', '13:00'];
  const skillsByModality = {};
  MODALITIES.forEach(mod => {
    const modKey = mod.toLowerCase();
    skillsByModality[modKey] = {};
    SKILLS.forEach(skill => {
      skillsByModality[modKey][skill] = '-1';
    });
  });
  return {
    task: taskName,
    row_type: 'gap',
    training: false,
    modifier: resolveDayModifier(taskConfig?.modifier, targetDay),
    counts_for_hours: taskConfig?.counts_for_hours === true,
    start_time: startTime,
    end_time: endTime,
    base_skills_by_modality: skillsByModality,
    skills_by_modality: skillsByModality,
  };
}

function getTaskPreviewEndpoint(tab) {
  return tab === 'today'
    ? '/api/live-schedule/resolve-task-preview'
    : '/api/prep-next-day/resolve-task-preview';
}

async function fetchTaskPreview(tab, payload) {
  const requestPayload = { ...(payload || {}) };
  if (tab === 'tomorrow' && prepTargetDate) {
    requestPayload.target_date = prepTargetDate;
  }

  const response = await fetch(getTaskPreviewEndpoint(tab), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(requestPayload),
  });

  let data = {};
  try {
    data = await response.json();
  } catch (_error) {
    data = {};
  }

  if (!response.ok) {
    throw new Error(data.error || 'Task preview failed');
  }

  return data;
}

function replaceDraftShiftPreviewState(shiftIdx, preview) {
  if (!editPlanDraft || !editPlanDraft.shifts) return;
  const shift = editPlanDraft.shifts[shiftIdx];
  if (!shift) return;

  updateEditPlanDraftShift(shiftIdx, {
    tasks: preview.task,
    start_time: preview.start_time,
    end_time: preview.end_time,
    Modifier: preview.modifier,
    counts_for_hours: preview.counts_for_hours,
    training: preview.training,
    row_type: preview.row_type,
  });

  const previewSkills = preview.skills_by_modality || {};
  const previewBaseSkills = preview.base_skills_by_modality || previewSkills;
  const modalityKeys = new Set([
    ...Object.keys(shift.modalities || {}),
    ...Object.keys(previewSkills),
  ]);

  modalityKeys.forEach(modKey => {
    if (!shift.modalities[modKey]) {
      shift.modalities[modKey] = {
        skills: {},
        baseSkills: {},
        row_index: -1,
        materialize: true,
      };
    }
    shift.modalities[modKey].baseSkills = cloneSkillMap(previewBaseSkills[modKey] || {});
    shift.modalities[modKey].skills = cloneSkillMap(previewSkills[modKey] || {});
  });
}

async function refreshEditShiftFromPreview(shiftIdx, taskName, trainingEnabled = null) {
  const { tab, groupIdx } = currentEditEntry || {};
  const group = entriesData[tab]?.[groupIdx];
  if (!group || !editPlanDraft || !editPlanDraft.shifts?.[shiftIdx]) return;

  const shift = editPlanDraft.shifts[shiftIdx];
  const taskConfig = getTaskConfigByName(taskName);
  if (!taskConfig) return;

  const preview = taskConfig.type === 'gap'
    ? buildGapPreviewFromTaskConfig(taskName, taskConfig, getTargetWeekdayName(tab))
    : await fetchTaskPreview(tab, {
        worker: group.worker,
        task: taskName,
        training: trainingEnabled !== null ? Boolean(trainingEnabled) : (shift.training !== false),
        mode: 'edit',
        current_shift: shift,
      });

  replaceDraftShiftPreviewState(shiftIdx, preview);
  markDraftShiftMaterialized(shiftIdx);
  renderEditModalContent();
}

function applyPreviewToAddWorkerTask(task, preview) {
  if (!task || !preview) return;
  task.start_time = preview.start_time;
  task.end_time = preview.end_time;
  task.modifier = preview.modifier;
  task.counts_for_hours = preview.counts_for_hours;
  task.training = preview.training;
  task.baseSkillsByModality = cloneSkillMap(preview.base_skills_by_modality || {});
  task.skillsByModality = cloneSkillMap(preview.skills_by_modality || {});
}

async function refreshAddWorkerTaskPreview(idx) {
  const task = addWorkerModalState.tasks[idx];
  if (!task || !task.task) return;

  const workerInput = document.getElementById('add-worker-name-input');
  const inputValue = workerInput ? workerInput.value.trim() : '';
  const { id: workerId, fullName } = parseWorkerInput(inputValue);
  const workerValue = fullName || workerId;
  if (!workerValue) return;

  const taskConfig = getTaskConfigByName(task.task);
  if (!taskConfig) return;
  const preview = taskConfig.type === 'gap'
    ? buildGapPreviewFromTaskConfig(task.task, taskConfig, getTargetWeekdayName(addWorkerModalState.tab))
    : await fetchTaskPreview(addWorkerModalState.tab, {
        worker: workerValue,
        task: task.task,
        training: task.training !== false,
        mode: 'new',
      });
  applyPreviewToAddWorkerTask(task, preview);
}

async function refreshModalAddFormPreview() {
  const { tab, groupIdx } = currentEditEntry || {};
  const group = entriesData[tab]?.[groupIdx];
  if (!group) return;

  const taskSelect = document.getElementById('modal-add-task');
  const taskName = taskSelect?.value;
  const taskConfig = getTaskConfigByName(taskName);
  if (!taskConfig) return;

  const trainingEl = document.getElementById('modal-add-training');
  const trainingEnabled = taskConfig.type === 'gap' ? false : (trainingEl ? trainingEl.checked : (taskConfig.training !== false));
  const preview = taskConfig.type === 'gap'
    ? buildGapPreviewFromTaskConfig(taskName, taskConfig, getTargetWeekdayName(tab))
    : await fetchTaskPreview(tab, {
        worker: group.worker,
        task: taskName,
        training: trainingEnabled,
        mode: 'new',
      });

  document.getElementById('modal-add-start').value = preview.start_time;
  document.getElementById('modal-add-end').value = preview.end_time;
  document.getElementById('modal-add-modifier').value = preview.modifier;

  const countsEl = document.getElementById('modal-add-counts-hours');
  if (countsEl) {
    countsEl.checked = preview.counts_for_hours === true;
    updateHoursToggleLabel(countsEl);
  }

  if (trainingEl) {
    trainingEl.checked = preview.training === true;
    trainingEl.disabled = preview.row_type === 'gap';
    updateTrainingToggleLabel(trainingEl);
  }

  const previewSkills = preview.skills_by_modality || {};
  MODALITIES.forEach(mod => {
    const modKey = mod.toLowerCase();
    SKILLS.forEach(skill => {
      const el = document.getElementById(`modal-add-${modKey}-skill-${skill}`);
      if (!el) return;
      const value = previewSkills[modKey]?.[skill];
      setModalAddSkillValue(el, value !== undefined ? value : 0, preview.training === true);
    });
  });
}

async function onEditShiftTaskChange(shiftIdx, taskName, options = {}) {
  const taskConfig = getTaskConfigByName(taskName);
  if (!taskConfig) return;
  const { tab, groupIdx } = currentEditEntry || {};
  const currentShift = getModalShifts(entriesData[tab]?.[groupIdx])[shiftIdx];
  const trainingEnabled = taskConfig.type === 'gap'
    ? false
    : (options.trainingEnabled !== undefined ? Boolean(options.trainingEnabled) : (currentShift?.training !== false));
  try {
    await refreshEditShiftFromPreview(shiftIdx, taskName, trainingEnabled);
  } catch (error) {
    showMessage('error', error.message);
  }
}

async function onEditShiftTrainingChange(shiftIdx, trainingEnabled) {
  const { tab, groupIdx } = currentEditEntry || {};
  const group = entriesData[tab]?.[groupIdx];
  if (!group) return;

  const shift = getModalShifts(group)[shiftIdx];
  if (!shift) return;

  const taskName = document.getElementById(`edit-shift-${shiftIdx}-task`)?.value || shift.task;
  if (!taskName) return;

  const trainingEl = document.getElementById(`edit-shift-${shiftIdx}-training`);
  if (trainingEl) {
    trainingEl.checked = trainingEnabled;
    updateTrainingToggleLabel(trainingEl);
  }
  try {
    await refreshEditShiftFromPreview(shiftIdx, taskName, trainingEnabled);
  } catch (error) {
    showMessage('error', error.message);
  }
}

// Delete shift from edit modal
async function deleteShiftFromModal(shiftIdx) {
  const { tab, groupIdx } = currentEditEntry || {};
  const group = entriesData[tab]?.[groupIdx];
  if (!group) return;

  setEditPlanDraftFromGroup(group);
  const shifts = getModalShifts(group);
  const shift = shifts[shiftIdx];
  if (!shift) return;

  const isLastShift = shifts.length === 1;
  const workerLabel = getWorkerDisplayName(group.worker);
  const confirmMessage = isLastShift
    ? `Delete this shift (${shift.start_time}-${shift.end_time})? This is the last shift for ${workerLabel}, so the worker will be removed. Continue?`
    : `Delete this shift (${shift.start_time}-${shift.end_time})?`;

  if (!confirm(confirmMessage)) return;

  const updatedShifts = [...shifts];
  updatedShifts.splice(shiftIdx, 1);
  if (editPlanDraft) {
    editPlanDraft.shifts = updatedShifts;
  }
  renderEditModalContent();
}



// Update shift fields in the modal draft
async function updateShiftFromModal(shiftIdx, updates) {
  const { tab, groupIdx } = currentEditEntry || {};
  const group = entriesData[tab]?.[groupIdx];
  if (!group) return;
  updateEditPlanDraftShift(shiftIdx, updates);
  markDraftShiftMaterialized(shiftIdx);
  applyModalEditModeUI();
}

// Update a single skill in the modal draft
async function updateShiftSkillFromModal(shiftIdx, modKey, skill, value) {
  const { tab, groupIdx } = currentEditEntry || {};
  const group = entriesData[tab]?.[groupIdx];
  if (!group) return;

  const shifts = getModalShifts(group);
  const shift = shifts[shiftIdx];
  if (!shift) return;

  const modData = shift.modalities[modKey];
  if (!modData) return;
  const normalizedValue = normalizeSkillValueJS(value);
  const effectiveValue = updateEditPlanDraftShiftSkill(shiftIdx, modKey, skill, normalizedValue);
  markDraftModalityMaterialized(shiftIdx, modKey);
  const skillSelect = document.getElementById(`edit-shift-${shiftIdx}-${modKey}-skill-${skill}`);
  if (skillSelect && effectiveValue !== null && effectiveValue !== undefined) {
    skillSelect.value = displaySkillValue(effectiveValue);
    syncSkillValueControlClass(skillSelect, effectiveValue);
  }
  updateEditPlanDraftShiftSkills(shiftIdx, { [modKey]: { [skill]: effectiveValue } });
  applyModalEditModeUI();
}

function isValidTimeValue(value) {
  return /^([01]\d|2[0-3]):[0-5]\d$/.test(value);
}

function commitModalTimeEdit(shiftIdx, field, inputEl) {
  if (!inputEl || !isValidTimeValue(inputEl.value)) return;
  const shift = getCurrentModalShift(shiftIdx);
  if (shift && shift[field] === inputEl.value) return;
  updateShiftFromModal(shiftIdx, { [field]: inputEl.value });
}

function commitModalTimeOnEnter(event, shiftIdx, field, inputEl) {
  if (event.key !== 'Enter') return;
  event.preventDefault();
  if (inputEl) inputEl.blur();
}


function getCurrentModalShift(shiftIdx) {
  const { tab, groupIdx } = currentEditEntry || {};
  const group = entriesData[tab]?.[groupIdx];
  if (!group) return null;
  const shifts = getModalShifts(group);
  return shifts?.[shiftIdx] || null;
}

function reopenEditModalForWorker(tab, workerName, formState = null) {
  const updatedGroupIdx = entriesData[tab]?.findIndex(entry => entry.worker === workerName);
  if (updatedGroupIdx === undefined || updatedGroupIdx < 0) {
    return false;
  }
  const updatedGroup = entriesData[tab]?.[updatedGroupIdx];
  clearEditPlanDraft();
  setEditPlanDraftFromGroup(updatedGroup, { force: true });
  currentEditEntry = {
    tab,
    groupIdx: updatedGroupIdx,
    worker: workerName,
    openedWorkerRevision: updatedGroup?.worker_revision || getWorkerRevision(tab, workerName),
  };
  renderEditModalContent();
  if (formState) {
    restoreModalAddFormState(formState);
  }
  return true;
}

function captureModalState() {
  const modalContent = document.getElementById('modal-content');
  const activeEl = document.activeElement;
  return {
    scrollTop: modalContent ? modalContent.scrollTop : 0,
    activeId: activeEl && activeEl.id ? activeEl.id : null,
    selectionStart: activeEl && typeof activeEl.selectionStart === 'number' ? activeEl.selectionStart : null,
    selectionEnd: activeEl && typeof activeEl.selectionEnd === 'number' ? activeEl.selectionEnd : null
  };
}

function restoreModalState(state) {
  if (!state) return;
  const modalContent = document.getElementById('modal-content');
  if (modalContent && typeof state.scrollTop === 'number') {
    modalContent.scrollTop = state.scrollTop;
  }
  if (state.activeId) {
    const activeEl = document.getElementById(state.activeId);
    if (activeEl && typeof activeEl.focus === 'function') {
      activeEl.focus();
      if (typeof activeEl.setSelectionRange === 'function' && state.selectionStart !== null && state.selectionEnd !== null) {
        activeEl.setSelectionRange(state.selectionStart, state.selectionEnd);
      }
    }
  }
}


// Delete shift inline from quick edit mode
async function deleteShiftInline(tab, groupIdx, shiftIdx) {
  const group = entriesData[tab]?.[groupIdx];
  if (!group) return;

  const shifts = getTableShifts(group);
  const shift = shifts[shiftIdx];
  if (!shift) return;

  if (!confirm(`Delete this shift (${shift.start_time}-${shift.end_time})?`)) return;

  // Queue delete for save, and hide shift from view immediately
  Object.entries(shift.modalities).forEach(([modKey, modData]) => {
    if (modData.row_index === undefined || modData.row_index < 0) return;
    const key = `delete-${modKey}-${modData.row_index}`;
    pendingChanges[tab][key] = {
      modality: modKey,
      row_index: modData.row_index,
      verify_ppl: group.worker,
      isDelete: true
    };
    const updateKey = `${modKey}-${modData.row_index}`;
    delete pendingChanges[tab][updateKey];
  });

  shift.deleted = true;
  updateSaveButtonCount(tab);
  renderTable(tab);
  showMessage('success', 'Shift queued for deletion');
}

// Handle task change in modal add shift section
function setModalAddSkillValue(selectEl, rawValue, trainingEnabled) {
  if (!selectEl) return;
  const normalized = normalizeSkillValueJS(rawValue);
  selectEl.dataset.baseValue = normalized.toString();
  const effectiveValue = applyTrainingToSkillValue(normalized, trainingEnabled);
  selectEl.value = displaySkillValue(effectiveValue);
  syncSkillValueControlClass(selectEl, effectiveValue);
}

function onModalAddSkillChange(selectEl) {
  const trainingEl = document.getElementById('modal-add-training');
  setModalAddSkillValue(selectEl, selectEl?.value, trainingEl ? trainingEl.checked : true);
}

async function onModalAddTrainingChange(trainingEnabled) {
  try {
    await refreshModalAddFormPreview();
  } catch (error) {
    showMessage('error', error.message);
  }
}

async function onModalTaskChange() {
  const taskSelect = document.getElementById('modal-add-task');
  const option = taskSelect?.options[taskSelect.selectedIndex];
  if (!option || !option.value) {
    return;
  }
  try {
    await refreshModalAddFormPreview();
  } catch (error) {
    showMessage('error', error.message);
  }
}

// Save the current state of the modal add form (to preserve user edits during re-renders)
function saveModalAddFormState() {
  const formState = {};
  const taskSelect = document.getElementById('modal-add-task');
  if (taskSelect) formState.task = taskSelect.value;
  const startInput = document.getElementById('modal-add-start');
  if (startInput) formState.start = startInput.value;
  const endInput = document.getElementById('modal-add-end');
  if (endInput) formState.end = endInput.value;
  const modifierInput = document.getElementById('modal-add-modifier');
  if (modifierInput) formState.modifier = modifierInput.value;
  const countsCheckbox = document.getElementById('modal-add-counts-hours');
  if (countsCheckbox) formState.countsForHours = countsCheckbox.checked;
  const trainingCheckbox = document.getElementById('modal-add-training');
  if (trainingCheckbox) formState.training = trainingCheckbox.checked;

  // Save skill values for all modalities
  formState.skills = {};
  MODALITIES.forEach(mod => {
    const modKey = mod.toLowerCase();
    formState.skills[modKey] = {};
    SKILLS.forEach(skill => {
      const el = document.getElementById(`modal-add-${modKey}-skill-${skill}`);
      if (el) {
        formState.skills[modKey][skill] = {
          value: el.value,
          baseValue: el.dataset.baseValue
        };
      }
    });
  });
  return formState;
}

// Restore the modal add form state (after re-render)
function restoreModalAddFormState(formState) {
  if (!formState) return;
  const taskSelect = document.getElementById('modal-add-task');
  if (taskSelect && formState.task !== undefined) taskSelect.value = formState.task;
  const startInput = document.getElementById('modal-add-start');
  if (startInput && formState.start !== undefined) startInput.value = formState.start;
  const endInput = document.getElementById('modal-add-end');
  if (endInput && formState.end !== undefined) endInput.value = formState.end;
  const modifierInput = document.getElementById('modal-add-modifier');
  if (modifierInput && formState.modifier !== undefined) modifierInput.value = formState.modifier;
  const countsCheckbox = document.getElementById('modal-add-counts-hours');
  if (countsCheckbox && formState.countsForHours !== undefined) {
    countsCheckbox.checked = formState.countsForHours;
    // Update the label styling
    const label = countsCheckbox.parentElement?.querySelector('.hours-toggle-label');
    if (label) {
      label.textContent = formState.countsForHours ? 'Counts' : 'No count';
      label.className = `hours-toggle-label ${formState.countsForHours ? 'counts' : 'no-count'}`;
    }
  }
  const trainingCheckbox = document.getElementById('modal-add-training');
  if (trainingCheckbox && formState.training !== undefined) {
    trainingCheckbox.checked = formState.training;
    updateTrainingToggleLabel(trainingCheckbox);
  }

  // Restore skill values
  if (formState.skills) {
    MODALITIES.forEach(mod => {
      const modKey = mod.toLowerCase();
      const modSkills = formState.skills[modKey] || {};
      SKILLS.forEach(skill => {
        const el = document.getElementById(`modal-add-${modKey}-skill-${skill}`);
        if (el && modSkills[skill] !== undefined) {
          const saved = modSkills[skill];
          if (saved && typeof saved === 'object') {
            el.value = saved.value;
            if (saved.baseValue !== undefined) el.dataset.baseValue = saved.baseValue;
          } else {
            el.value = saved;
            el.dataset.baseValue = saved;
          }
          syncSkillValueControlClass(el);
        }
      });
    });
  }
}

// Initialize modal add-shift form with sensible defaults from config and roster
function initializeModalAddForm() {
  const taskSelect = document.getElementById('modal-add-task');
  if (!taskSelect) return;

  // The dropdown now auto-selects first shift via renderTaskOptionsWithGroups(_, _, true)
  // Call onModalTaskChange to populate times/skills based on the selected task
  if (taskSelect.value) {
    onModalTaskChange();
  } else {
    // No task selected: still populate with roster defaults if present
    // Roster structure is modality-scoped: { modality: { skill: value } }
    const { tab, groupIdx } = currentEditEntry || {};
    const group = entriesData[tab]?.[groupIdx];
    const workerRoster = group ? WORKER_SKILLS[group.worker] : null;
    MODALITIES.forEach(mod => {
      const modKey = mod.toLowerCase();
      const modalitySkills = workerRoster ? (workerRoster[modKey] || {}) : {};
      SKILLS.forEach(skill => {
        const el = document.getElementById(`modal-add-${modKey}-skill-${skill}`);
        if (el) {
          const val = modalitySkills[skill] !== undefined ? modalitySkills[skill] : 0;
          setModalAddSkillValue(el, val, true);
        }
      });
    });
  }
}

// Add shift from modal (staged locally until Save)
async function addShiftFromModal() {
  const { tab, groupIdx } = currentEditEntry || {};
  const group = entriesData[tab]?.[groupIdx];
  if (!group) return;

  const taskSelect = document.getElementById('modal-add-task');
  const taskName = taskSelect?.value;
  if (!taskName) {
    showMessage('error', 'Please pick a role/task');
    return;
  }

  // All modalities are always active
  const selectedModalities = MODALITIES.map(m => m.toLowerCase());

  const startTime = document.getElementById('modal-add-start').value;
  const endTime = document.getElementById('modal-add-end').value;
  const modifier = parseFloat(document.getElementById('modal-add-modifier').value) || 1.0;
  const countsHoursEl = document.getElementById('modal-add-counts-hours');
  const countsForHours = countsHoursEl ? countsHoursEl.checked : true;
  const isGap = isGapTask(taskName);
  const taskConfig = getTaskConfigByName(taskName);
  const trainingEl = document.getElementById('modal-add-training');
  const trainingEnabled = isGap ? false : (trainingEl ? trainingEl.checked : (taskConfig?.training !== false));
  const taskKey = (taskName || '').trim();
  const addedShiftKey = `${startTime}-${endTime}-${isGap ? 'gap' : 'shift'}-${taskKey}`;

  if (modalMode === 'edit-plan') {
    if (!editPlanDraft) {
      showMessage('error', 'No edit plan available');
      return;
    }
    const modalities = {};
    selectedModalities.forEach(modKey => {
      const baseSkills = {};
      const skills = {};
      SKILLS.forEach(skill => {
        if (isGap) {
          baseSkills[skill] = -1;
          skills[skill] = -1;
          return;
        }
        const el = document.getElementById(`modal-add-${modKey}-skill-${skill}`);
        const rawValue = normalizeSkillValueJS(el?.dataset.baseValue !== undefined ? el.dataset.baseValue : (el ? el.value : 0));
        baseSkills[skill] = rawValue;
        skills[skill] = applyTrainingToSkillValue(rawValue, trainingEnabled);
      });
      modalities[modKey] = {
        skills,
        baseSkills,
        row_index: -1,
        modifier,
        materialize: true
      };
    });

      editPlanDraft.shifts = [
        ...(editPlanDraft.shifts || []),
        {
        start_time: startTime,
        end_time: endTime,
        modifier,
        counts_for_hours: countsForHours,
        training: trainingEnabled,
        task: taskName,
        row_type: isGap ? 'gap' : 'shift',
        is_gap_entry: isGap,
        modalities,
        timeSegments: [{ start: startTime, end: endTime }],
      }
    ];
    showMessage('success', `Added new ${isGap ? 'gap' : 'shift'} for ${getWorkerDisplayName(group.worker)}. Save edits to apply.`);
    lastAddedShiftMeta = { worker: group.worker, shiftKey: addedShiftKey };
    renderEditModalContent();
    return;
  }

  const addWorkerEndpoint = tab === 'today' ? '/api/live-schedule/add-worker' : '/api/prep-next-day/add-worker';
  const addGapEndpoint = tab === 'today' ? '/api/live-schedule/add-gap' : '/api/prep-next-day/add-gap';

  try {
    if (isGap) {
      const rowIndexByModality = new Map();
      group.allEntries.forEach(entry => {
        if (entry.row_index !== undefined && entry.row_index !== null && entry.row_index >= 0) {
          if (!rowIndexByModality.has(entry.modality)) {
            rowIndexByModality.set(entry.modality, entry.row_index);
          }
        }
      });

      if (rowIndexByModality.size === 0) {
        throw new Error('No existing row index found for this worker; reload and try again.');
      }

      for (const [modality, rowIndex] of rowIndexByModality.entries()) {
        await postJsonWithSnapshot(tab, addGapEndpoint, {
          modality,
          row_index: rowIndex,
          gap_type: getTaskPersistedName(taskName),
          gap_start: startTime,
          gap_end: endTime,
          gap_counts_for_hours: countsForHours
        }, {
          reloadOnConflict: true,
        });
      }
    } else {
      for (const modKey of selectedModalities) {
        const skills = {};
        SKILLS.forEach(skill => {
          const el = document.getElementById(`modal-add-${modKey}-skill-${skill}`);
          skills[skill] = normalizeSkillValueJS(el ? el.value : 0);
        });
        await postJsonWithSnapshot(tab, addWorkerEndpoint, {
          modality: modKey,
          worker_data: {
            PPL: group.worker,
            start_time: startTime,
            end_time: endTime,
            Modifier: modifier,
            counts_for_hours: countsForHours,
            training: trainingEnabled,
            tasks: taskName,
            row_type: 'shift',
            materialize: true,
            ...skills
          }
        }, {
          reloadOnConflict: true,
        });
      }
    }
    showMessage('success', `Added new ${isGap ? 'gap' : 'shift'} for ${getWorkerDisplayName(group.worker)}`);

    lastAddedShiftMeta = { worker: group.worker, shiftKey: addedShiftKey };
    await loadData();
    // Re-render modal to show updated shifts instead of closing
    renderEditModalContent();
  } catch (error) {
    if (error.isConflict) {
      return;
    }
    showMessage('error', error.message);
  }
}

function onEditGapTypeChange() {
  const select = document.getElementById('edit-gap-type');
  const startInput = document.getElementById('edit-gap-start');
  const endInput = document.getElementById('edit-gap-end');

  if (!select.value) {
    startInput.disabled = true;
    endInput.disabled = true;
    return;
  }

  startInput.disabled = false;
  endInput.disabled = false;

  const option = select.options[select.selectedIndex];
  if (option.value !== 'custom' && option.dataset.times) {
    const times = JSON.parse(option.dataset.times);
    // Use target day based on current tab (today vs tomorrow)
    const { tab } = currentEditEntry || {};
    const targetDay = getTargetWeekdayName(tab || currentTab);
    const parsedTimes = getGapTimeRange({ times }, targetDay);
    if (parsedTimes) {
      const [start, end] = parsedTimes;
      startInput.value = start;
      endInput.value = end;
    }
  }
}

function applySkillValues(skillMap = {}) {
  SKILLS.forEach(skill => {
    if (skillMap[skill] !== undefined) {
      const el = document.getElementById(`edit-skill-${skill}`);
      if (el) {
        el.value = skillMap[skill];
      }
    }
  });
}


// Apply worker skill preset for a specific modality
function applyWorkerSkillPresetForModality(workerName, modKey) {
  const workerRoster = WORKER_SKILLS[workerName];
  if (!workerRoster) {
    showMessage('error', `No skill preset found for ${getWorkerDisplayName(workerName)}`);
    return;
  }

  // Roster structure is modality-scoped: { modality: { skill: value } }
  const modalitySkills = workerRoster[modKey] || {};

  SKILLS.forEach(skill => {
    const el = document.getElementById(`edit-${modKey}-skill-${skill}`);
    if (el && modalitySkills[skill] !== undefined) {
      // Limit roster presets to 0/-1; positive values are reserved for manual/CSV edits
      const val = modalitySkills[skill];
      const effectiveValue = val > 0 ? 0 : val;
      el.value = displaySkillValue(effectiveValue);
      syncSkillValueControlClass(el, effectiveValue);
    }
  });
}

// Apply worker skill preset for a specific modality in a specific shift
function applyWorkerSkillPresetForShiftModality(groupIdx, shiftIdx, modKey) {
  const { tab } = currentEditEntry || {};
  const group = entriesData[tab]?.[groupIdx];
  const workerName = group?.worker;
  const workerRoster = workerName ? WORKER_SKILLS[workerName] : null;
  if (!workerRoster) {
    showMessage('error', `No skill preset found for ${workerName ? getWorkerDisplayName(workerName) : 'worker'}`);
    return;
  }

  // Roster structure is modality-scoped: { modality: { skill: value } }
  const modalitySkills = workerRoster[modKey] || {};

  SKILLS.forEach(skill => {
    const el = document.getElementById(`edit-shift-${shiftIdx}-${modKey}-skill-${skill}`);
    if (el && modalitySkills[skill] !== undefined) {
      // Limit roster presets to 0/-1; positive values are reserved for manual/CSV edits
      const val = modalitySkills[skill];
      const effectiveValue = val > 0 ? 0 : val;
      el.value = displaySkillValue(effectiveValue);
      syncSkillValueControlClass(el, effectiveValue);
    }
  });
}

// Apply preset from config to all modalities in a shift
async function applyPresetToShift(shiftIdx, taskName) {
  if (!taskName) return;

  const task = getTaskConfigByName(taskName);
  if (!task) {
    showMessage('error', `Preset not found: ${taskName}`);
    return;
  }

  const { tab, groupIdx } = currentEditEntry || {};
  const group = entriesData[tab]?.[groupIdx];
  if (!group) return;

  const shift = getModalShifts(group)[shiftIdx];
  if (!shift) return;
  try {
    await refreshEditShiftFromPreview(shiftIdx, taskName, shift.training !== false);
  } catch (error) {
    showMessage('error', error.message);
  }
}

// Apply worker roster skills to all modalities in a shift
function applyWorkerRosterToShift(shiftIdx) {
  const { tab, groupIdx } = currentEditEntry || {};
  const group = entriesData[tab]?.[groupIdx];
  if (!group) return;

  const workerRoster = WORKER_SKILLS[group.worker];
  if (!workerRoster) {
    showMessage('error', `No skill preset found for ${getWorkerDisplayName(group.worker)}`);
    return;
  }

  const shift = getModalShifts(group)[shiftIdx];
  if (!shift) return;

  // Apply skills to all modalities in this shift
  // Roster structure is modality-scoped: { modality: { skill: value } }
  Object.keys(shift.modalities).forEach(modKey => {
    const modalitySkills = workerRoster[modKey] || {};

    SKILLS.forEach(skill => {
      const el = document.getElementById(`edit-shift-${shiftIdx}-${modKey}-skill-${skill}`);
      if (el && modalitySkills[skill] !== undefined) {
        // Limit roster presets to 0/-1; positive values are reserved for manual/CSV edits
        const val = modalitySkills[skill];
        const effectiveValue = val > 0 ? 0 : val;
        el.value = displaySkillValue(effectiveValue);
        syncSkillValueControlClass(el, effectiveValue);
      }
    });
  });
}

async function saveModalChanges() {
  if (!currentEditEntry) return;

  const { tab, groupIdx } = currentEditEntry;
  const group = entriesData[tab][groupIdx];
  if (!group) return;

  if (modalMode !== 'edit-plan') {
    showMessage('error', 'Unexpected modal mode. Reopen the edit dialog and try again.');
    return;
  }
  if (!editPlanDraft || !editPlanDraft.worker) {
    showMessage('error', 'No edit plan available');
    return;
  }
  const applyEndpoint = tab === 'today'
    ? '/api/live-schedule/apply-worker-plan'
    : '/api/prep-next-day/apply-worker-plan';
  const formState = saveModalAddFormState();
  const modalState = captureModalState();
  try {
    syncEditPlanDraftFromModal();
    const persistedShifts = (editPlanDraft.shifts || []).map(shift => ({
      ...shift,
      task: getTaskPersistedName(shift.task),
      tasks: getTaskPersistedName(shift.tasks || shift.task),
    }));
    await postJsonWithSnapshot(tab, applyEndpoint, {
      worker: editPlanDraft.worker,
      shifts: persistedShifts,
      worker_revision: currentEditEntry?.openedWorkerRevision || getWorkerRevision(tab, editPlanDraft.worker),
    }, {
      reloadOnConflict: true,
      includeSnapshotVersion: false,
    });
    clearEditPlanDraft();
    closeModal();
    showMessage('success', 'Worker entries updated');
    await loadData();
  } catch (error) {
    if (error.isConflict) {
      const workerName = editPlanDraft?.worker || group.worker;
      if (reopenEditModalForWorker(tab, workerName, formState)) {
        restoreModalState(modalState);
      }
      return;
    }
    showMessage('error', error.message);
  }
}

function syncEditPlanDraftFromModal() {
  if (!currentEditEntry || !editPlanDraft) return;
  const { tab, groupIdx } = currentEditEntry;
  const group = entriesData[tab]?.[groupIdx];
  if (!group) return;
  const shifts = getModalShifts(group);
  shifts.forEach((shift, shiftIdx) => {
    const taskEl = document.getElementById(`edit-shift-${shiftIdx}-task`);
    const startEl = document.getElementById(`edit-shift-${shiftIdx}-start`);
    const endEl = document.getElementById(`edit-shift-${shiftIdx}-end`);
    const modifierEl = document.getElementById(`edit-shift-${shiftIdx}-modifier`);
    const trainingEl = document.getElementById(`edit-shift-${shiftIdx}-training`);
    const countsEl = document.getElementById(`edit-shift-${shiftIdx}-counts-hours`);

    const taskName = taskEl?.value || shift.task || '';
    const taskConfig = getTaskConfigByName(taskName);
    const isGapTask = taskConfig?.type === 'gap';

    const updates = {};
    if (taskName) updates.tasks = taskName;
    if (startEl && isValidTimeValue(startEl.value)) updates.start_time = startEl.value;
    if (endEl && isValidTimeValue(endEl.value)) updates.end_time = endEl.value;
    if (modifierEl) updates.Modifier = parseFloat(modifierEl.value) || 1.0;
    if (trainingEl) updates.training = trainingEl.checked;
    if (countsEl) updates.counts_for_hours = countsEl.checked;

    if (taskConfig) {
      updates.row_type = isGapTask ? 'gap' : 'shift';
      updates.training = isGapTask ? false : Boolean(updates.training);
      updates.counts_for_hours = isGapTask ? getGapCountsForHours(taskName) : Boolean(updates.counts_for_hours);
    }

    if (Object.keys(updates).length) {
      updateEditPlanDraftShift(shiftIdx, updates);
    }

    const skillUpdatesByMod = {};
    Object.keys(shift.modalities || {}).forEach(modKey => {
      SKILLS.forEach(skill => {
        const el = document.getElementById(`edit-shift-${shiftIdx}-${modKey}-skill-${skill}`);
        if (!skillUpdatesByMod[modKey]) skillUpdatesByMod[modKey] = {};
        if (isGapTask) {
          skillUpdatesByMod[modKey][skill] = updateEditPlanDraftShiftSkill(shiftIdx, modKey, skill, -1, false);
          if (el) el.value = '-1';
          return;
        }
        if (el) {
          const normalizedSkill = normalizeSkillValueJS(el.value);
          skillUpdatesByMod[modKey][skill] = updateEditPlanDraftShiftSkill(
            shiftIdx,
            modKey,
            skill,
            normalizedSkill,
            updates.training !== undefined ? updates.training : shift.training !== false
          );
        }
      });
    });
    if (Object.keys(skillUpdatesByMod).length) {
      updateEditPlanDraftShiftSkills(shiftIdx, skillUpdatesByMod);
    }
  });
}

function closeModal() {
  document.getElementById('edit-modal').classList.remove('show');
  currentEditEntry = null;
  clearEditPlanDraft();
  if (modalMode === 'add-worker') {
    resetAddWorkerModalState();
  }
  setModalMode('edit');
}

function setModalMode(mode) {
  modalMode = mode;
  const saveButton = document.getElementById('modal-save-button');
  if (!saveButton) return;
  if (mode === 'add-worker') {
    saveButton.className = 'btn btn-success';
  } else if (mode === 'edit-plan') {
    saveButton.className = 'btn btn-primary';
  } else {
    // Edit mode: all edits are live, no Save button needed
    saveButton.style.display = 'none';
  }
  applyModalEditModeUI();
}

function updateModalSaveButtonLabel() {
  const saveButton = document.getElementById('modal-save-button');
  if (!saveButton) return;

  if (modalMode === 'add-worker') {
    saveButton.textContent = 'Add Worker';
    saveButton.title = '';
    return;
  }

  if (modalMode === 'edit-plan') {
    const hasPendingDraft = typeof hasEditPlanPendingChanges === 'function' && hasEditPlanPendingChanges();
    saveButton.textContent = hasPendingDraft ? 'Save Edits*' : 'Save Edits';
    saveButton.title = hasPendingDraft ? '* Pending changes in this edit dialog' : '';
  }
}

function applyModalEditModeUI() {
  const saveButton = document.getElementById('modal-save-button');
  if (saveButton) {
    if (modalMode === 'add-worker') {
      saveButton.style.display = '';
    } else if (modalMode === 'edit-plan') {
      saveButton.style.display = '';
    } else {
      saveButton.style.display = 'none';
    }
  }
  updateModalSaveButtonLabel();
}

function saveModalAction() {
  if (modalMode === 'add-worker') {
    saveAddWorkerModal();
    return;
  }
  if (modalMode === 'edit-plan') {
    saveModalChanges();
    return;
  }
  saveModalChanges();
}

// =============================================
// ADD WORKER MODAL FUNCTIONS
// =============================================

function openAddWorkerModal(tab) {
  addWorkerModalState.tab = tab;
  addWorkerModalState.tasks = [];
  addWorkerModalState.containerId = 'modal-content';
  // Start with one empty task
  addTaskToAddWorkerModal();
  renderAddWorkerModalContent();
  setModalMode('add-worker');
  document.getElementById('modal-title').textContent = tab === 'today' ? 'Add Worker (Today)' : 'Add Worker (Tomorrow)';
  document.getElementById('edit-modal').classList.add('show');
}

function resetAddWorkerModalState() {
  addWorkerModalState.tab = null;
  addWorkerModalState.tasks = [];
  addWorkerModalState.containerId = 'modal-content';
}

function addTaskToAddWorkerModal() {
  // Find default task to prefill (prefer regular shifts over blocker shifts, then gaps)
  const defaultTask =
    TASK_ROLES.find(t => t.type === 'shift' && t.counts_for_hours !== false) ||
    TASK_ROLES.find(t => t.type === 'shift') ||
    TASK_ROLES[0] ||
    {};

  // Get day-specific times from task config
  const targetDay = getTargetWeekdayName(addWorkerModalState.tab || currentTab);
  const initialTaskState = buildAddWorkerTaskState(defaultTask, targetDay);

  addWorkerModalState.tasks.push({
    task: defaultTask.name || '',
    ...initialTaskState
  });
}

function removeTaskFromAddWorkerModal(idx) {
  if (addWorkerModalState.tasks.length <= 1) {
    showMessage('error', 'At least one task is required');
    return;
  }
  addWorkerModalState.tasks.splice(idx, 1);
  renderAddWorkerModalContent();
}

async function updateAddWorkerTask(idx, field, value) {
  if (!addWorkerModalState.tasks[idx]) return;
  const task = addWorkerModalState.tasks[idx];
  task[field] = value;

  // If the task changes, update times, modifier, and skill defaults from config.
  if (field === 'task') {
    const taskConfig = getTaskConfigByName(value);
    if (!taskConfig) {
      renderAddWorkerModalContent();
      return;
    }

    const targetDay = getTargetWeekdayName(addWorkerModalState.tab || currentTab);
    Object.assign(task, buildAddWorkerTaskState(taskConfig, targetDay));
  } else if (field === 'training') {
    task.training = Boolean(value);
    rebuildAddWorkerTaskSkills(task);
  }

  const workerInput = document.getElementById('add-worker-name-input');
  const inputValue = workerInput ? workerInput.value.trim() : '';
  const { id: workerId } = parseWorkerInput(inputValue);
  if (field === 'task' || field === 'training') {
    try {
      await refreshAddWorkerTaskPreview(idx);
    } catch (error) {
      showMessage('error', error.message);
    }
  } else if (workerId && WORKER_SKILLS[workerId]) {
    applyRosterToSkillsByModality(task.skillsByModality, workerId, task.baseSkillsByModality);
  }

  renderAddWorkerModalContent();
}

function updateAddWorkerSkill(idx, modality, skill, value) {
  if (!addWorkerModalState.tasks[idx]) return;
  const task = addWorkerModalState.tasks[idx];
  if (!task.baseSkillsByModality) task.baseSkillsByModality = {};
  if (!task.baseSkillsByModality[modality]) task.baseSkillsByModality[modality] = {};
  if (!task.skillsByModality[modality]) task.skillsByModality[modality] = {};

  const workerInput = document.getElementById('add-worker-name-input');
  const inputValue = workerInput ? workerInput.value.trim() : '';
  const { id: workerId } = parseWorkerInput(inputValue);
  if (workerId && WORKER_SKILLS[workerId]?.[modality]?.[skill] === -1) {
    task.baseSkillsByModality[modality][skill] = -1;
    task.skillsByModality[modality][skill] = -1;
    renderAddWorkerModalContent();
    return;
  }

  const raw = (value || '').toString().trim();
  const baseValue = raw === 'w' ? 'w' : (parseInt(raw, 10) || 0);
  task.baseSkillsByModality[modality][skill] = baseValue;
  task.skillsByModality[modality][skill] = applyTrainingToSkillValue(baseValue, task.training !== false);
}

// Helper: apply roster exclusions to skillsByModality (roster -1 always wins)
// Roster structure is modality-scoped: { modality: { skill: value } }
function applyRosterToSkillsByModality(skillsByModality, workerName, baseSkillsByModality = null) {
  if (!workerName || !WORKER_SKILLS[workerName]) return;
  const workerRoster = WORKER_SKILLS[workerName];
  MODALITIES.forEach(mod => {
    const modKey = mod.toLowerCase();
    if (!skillsByModality[modKey]) skillsByModality[modKey] = {};
    if (baseSkillsByModality && !baseSkillsByModality[modKey]) baseSkillsByModality[modKey] = {};
    // Get roster skills for this specific modality
    const modalityRoster = workerRoster[modKey] || {};
    SKILLS.forEach(skill => {
      // Roster -1 always wins (cannot be overridden)
      if (modalityRoster[skill] === -1) {
        skillsByModality[modKey][skill] = -1;
        if (baseSkillsByModality) {
          baseSkillsByModality[modKey][skill] = -1;
        }
      }
    });
  });
}

function rebuildAddWorkerTaskSkills(task) {
  if (!task) return;
  const trainingEnabled = task.training !== false;
  const baseSkillsByModality = task.baseSkillsByModality || {};
  const skillsByModality = {};

  MODALITIES.forEach(mod => {
    const modKey = mod.toLowerCase();
    const baseSkills = baseSkillsByModality[modKey] || {};
    skillsByModality[modKey] = {};
    SKILLS.forEach(skill => {
      const baseValue = baseSkills[skill] !== undefined ? baseSkills[skill] : 0;
      skillsByModality[modKey][skill] = applyTrainingToSkillValue(baseValue, trainingEnabled);
    });
  });

  task.skillsByModality = skillsByModality;
}

function createNeutralSkillsByModality(defaultValue = 0) {
  const result = {};
  MODALITIES.forEach(mod => {
    const modKey = mod.toLowerCase();
    result[modKey] = {};
    SKILLS.forEach(skill => {
      result[modKey][skill] = defaultValue;
    });
  });
  return result;
}

function buildAddWorkerTaskState(taskConfig, targetDay) {
  const config = taskConfig || {};
  const isGap = config.type === 'gap';
  const trainingEnabled = isGap ? false : (config.training !== false);
  const countsForHours = isGap ? false : (config.counts_for_hours !== false);
  const modifier = resolveDayModifier(config.modifier, targetDay);
  const baseSkillsByModality = createNeutralSkillsByModality(isGap ? -1 : 0);
  const skillsByModality = cloneSkillMap(baseSkillsByModality);
  const [startTime, endTime] = isGap
    ? (getGapTimeRange(config, targetDay) || ['12:00', '13:00'])
    : (() => {
        const times = getShiftTimes(config, targetDay);
        return [times.start, times.end];
      })();

  return {
    start_time: startTime,
    end_time: endTime,
    modifier,
    counts_for_hours: countsForHours,
    training: trainingEnabled,
    baseSkillsByModality,
    skillsByModality,
  };
}

async function onAddWorkerNameChange() {
  const workerInput = document.getElementById('add-worker-name-input');
  const inputValue = workerInput ? workerInput.value.trim() : '';
  if (!inputValue) return;

  // Parse display label / raw full name / ID and only refresh once the value resolves.
  const { fullName, id: workerId, matchedExisting } = parseWorkerInput(inputValue);

  if (!(fullName || matchedExisting || (workerId && WORKER_SKILLS[workerId]))) return;

  try {
    for (let idx = 0; idx < addWorkerModalState.tasks.length; idx += 1) {
      await refreshAddWorkerTaskPreview(idx);
    }
    renderAddWorkerModalContent();
  } catch (error) {
    showMessage('error', error.message);
  }
}

async function saveAddWorkerModal() {
  const workerInput = document.getElementById('add-worker-name-input');
  const inputValue = workerInput ? workerInput.value.trim() : '';

  if (!inputValue) {
    showMessage('error', 'Please enter a worker name');
    return;
  }

  // Parse "Full Name (ID)" format to extract the worker ID
  const { id: workerId, fullName } = parseWorkerInput(inputValue);
  const workerLabel = fullName || getWorkerDisplayName(workerId);

  if (addWorkerModalState.tasks.length === 0) {
    showMessage('error', 'Please add at least one task');
    return;
  }

  const { tab, tasks } = addWorkerModalState;
  const workerEndpoint = tab === 'today'
    ? '/api/live-schedule/apply-worker-plan'
    : '/api/prep-next-day/apply-worker-plan';

  try {
    const shifts = tasks.map(task => {
      const isGap = isGapTask(task.task);
      const trainingEnabled = isGap ? false : (task.training !== false);
      const modalities = {};
      const skillsByModality = task.skillsByModality || {};

      Object.entries(skillsByModality).forEach(([modKey, modSkills]) => {
        modalities[modKey] = {
          skills: { ...(modSkills || {}) },
          row_index: -1,
          materialize: true
        };
      });

      return {
        start_time: task.start_time,
        end_time: task.end_time,
        modifier: task.modifier,
        counts_for_hours: isGap ? task.counts_for_hours === true : task.counts_for_hours !== false,
        training: trainingEnabled,
        task: getTaskPersistedName(task.task),
        row_type: isGap ? 'gap' : 'shift',
        modalities
      };
    });

    await postJsonWithSnapshot(tab, workerEndpoint, {
      worker: workerLabel,
      shifts
    }, {
      reloadOnConflict: true,
    });

    closeModal();
    showMessage('success', `${getWorkerDisplayName(workerId)} added/updated`);
    await loadData();
  } catch (error) {
    if (error.isConflict) {
      return;
    }
    showMessage('error', error.message);
  }
}

function getGapCountsForHours(taskName) {
  const taskConfig = getTaskConfigByName(taskName);
  return taskConfig?.counts_for_hours === true;
}

// =============================================
// END ADD WORKER MODAL FUNCTIONS
// =============================================


// =============================================
// QUICK BREAK NOW FEATURE
// =============================================

/**
 * Add a break (gap) starting NOW for a worker.
 * Uses add-gap API to add gap to existing shifts.
 * Falls back to standalone gap entry if no shift exists at that time.
 * @param {string} tab - 'today' or 'tomorrow'
 * @param {number} gIdx - Group index
 * @param {number} [durationMinutes] - Duration in minutes (optional, defaults to QUICK_BREAK.duration_minutes)
 */
async function onQuickGap30(tab, gIdx, durationMinutes) {
  if (tab === 'tomorrow') {
    showMessage('error', 'Break NOW actions are disabled in prep mode.');
    return;
  }
  if (editMode[tab] || Object.keys(pendingChanges[tab] || {}).length > 0) {
    showMessage('error', 'Exit Quick Edit before adding a break.');
    return;
  }
  const group = entriesData[tab][gIdx];
  if (!group) {
    showMessage('error', 'Invalid worker group');
    return;
  }

  // Get current time (exact minute)
  const now = new Date();
  const currentMinutes = now.getHours() * 60 + now.getMinutes();
  const gapStart = formatMinutesToTime(currentMinutes);
  const duration = durationMinutes || QUICK_BREAK.duration_minutes;
  const gapEnd = addMinutes(gapStart, duration);
  const gapType = QUICK_BREAK.gap_type || 'Break';

  // If not in edit mode, show confirmation popup
  if (!editMode[tab]) {
    const msg = `Add ${duration}-min break for ${getWorkerDisplayName(group.worker)}?\n\nTime: ${gapStart} - ${gapEnd}`;
    if (!confirm(msg)) return;
  }

  try {
    // Create standalone gap intent rows atomically across modalities.
    const addEndpoint = tab === 'today' ? '/api/live-schedule/add-gap-batch' : '/api/prep-next-day/add-gap-batch';
    const rowIndexByModality = new Map();
    group.allEntries.forEach(entry => {
      if (entry.row_index !== undefined && entry.row_index !== null && entry.row_index >= 0) {
        if (!rowIndexByModality.has(entry.modality)) {
          rowIndexByModality.set(entry.modality, entry.row_index);
        }
      }
    });

    if (rowIndexByModality.size === 0) {
      throw new Error('No existing row index found for this worker; reload and try again.');
    }

    await postJsonWithSnapshot(tab, addEndpoint, {
      row_index_map: Object.fromEntries(rowIndexByModality.entries()),
      gap_type: gapType,
      gap_start: gapStart,
      gap_end: gapEnd,
      gap_counts_for_hours: getGapCountsForHours(gapType)
    }, {
      reloadOnConflict: true,
    });

    showMessage('success', `Added break (${gapStart}-${gapEnd}) for ${getWorkerDisplayName(group.worker)}`);
    await loadData();
  } catch (error) {
    if (error.isConflict) {
      return;
    }
    showMessage('error', error.message || 'Failed to add break');
  }
}

/** Format total minutes to HH:MM string */
function formatMinutesToTime(totalMinutes) {
  const hours = Math.floor(totalMinutes / 60) % 24;
  const mins = totalMinutes % 60;
  return `${String(hours).padStart(2, '0')}:${String(mins).padStart(2, '0')}`;
}

/** Add minutes to a time string (HH:MM format) */
function addMinutes(timeStr, minutes) {
  const [hours, mins] = timeStr.split(':').map(Number);
  return formatMinutesToTime(hours * 60 + mins + minutes);
}

/** Called from edit modal - shows duration popup */
function onQuickGapFromModal() {
  if (!currentEditEntry) {
    showMessage('error', 'No entry selected');
    return;
  }
  if (modalMode === 'edit-plan') {
    showMessage('info', 'Quick break is disabled in edit mode. Add a gap in the modal list instead.');
    return;
  }
  // Show break duration popup
  document.getElementById('break-popup').classList.add('show');
  document.getElementById('break-custom-minutes').value = '';
  clearBreakPresets();
  // Pre-select configured break duration as default
  selectBreakPreset(QUICK_BREAK.duration_minutes);
}

/** Track selected break duration */
let selectedBreakDuration = null;

/** Select a preset duration button */
function selectBreakPreset(minutes) {
  selectedBreakDuration = minutes;
  document.getElementById('break-custom-minutes').value = '';
  // Update button styles
  document.querySelectorAll('.break-presets button').forEach(btn => {
    btn.classList.toggle('selected', btn.textContent.includes(minutes + ' min'));
  });
}

/** Clear preset selection when custom input is used */
function clearBreakPresets() {
  document.querySelectorAll('.break-presets button').forEach(btn => {
    btn.classList.remove('selected');
  });
  selectedBreakDuration = null;
}

/** Close the break duration popup */
function closeBreakPopup() {
  document.getElementById('break-popup').classList.remove('show');
  selectedBreakDuration = null;
}

/** Confirm break duration and execute */
async function confirmBreakDuration() {
  // Get duration from custom input or preset
  const customInput = document.getElementById('break-custom-minutes').value;
  const duration = customInput ? parseInt(customInput, 10) : selectedBreakDuration;

  if (!duration || duration < 1) {
    showMessage('error', 'Please select or enter a break duration');
    return;
  }

  if (!currentEditEntry) {
    showMessage('error', 'No entry selected');
    closeBreakPopup();
    return;
  }

  const { tab, groupIdx } = currentEditEntry;
  const workerName = entriesData[tab]?.[groupIdx]?.worker || null;
  // Close popup, add gap (which calls loadData internally)
  closeBreakPopup();
  await onQuickGap30(tab, groupIdx, duration);
  // Re-render modal to show the new gap (data already loaded by onQuickGap30)
  if (workerName) {
    reopenEditModalForWorker(tab, workerName);
  }
}

// =============================================
// END QUICK BREAK NOW FEATURE
// =============================================


// Load from CSV
async function loadFromCSV(mode, options = {}) {
  const targetDate = mode === 'today' ? null : (document.getElementById('prep-target-date')?.value || prepTargetDate);
  const shouldConfirm = options.confirm !== false;
  const forceCsv = options.forceCsv !== false;

  if (mode === 'today') {
    const hasPendingChanges = Object.keys(pendingChanges.today || {}).length > 0;
    const message = hasPendingChanges
      ? 'HARD RELOAD TODAY will discard unsaved Quick Edit changes and reset today from the Master CSV. Continue?'
      : 'HARD RELOAD TODAY will reset today from the Master CSV. Continue?';
    if (shouldConfirm && !window.confirm(message)) {
      return;
    }
  } else {
    if (editMode.tomorrow) {
      showMessage('error', 'Exit Quick Edit before reloading the selected date.');
      return;
    }
    const hasPendingChanges = Object.keys(pendingChanges.tomorrow || {}).length > 0;
    const targetLabel = targetDate ? ` for ${targetDate}` : '';
    const message = hasPendingChanges
      ? `HARD RELOAD SELECTED DATE${targetLabel} will overwrite the current staged tomorrow changes and discard unsaved Quick Edit edits. Continue?`
      : `HARD RELOAD SELECTED DATE${targetLabel} will overwrite the current staged tomorrow data from the Master CSV. Continue?`;
    if (shouldConfirm && !window.confirm(message)) {
      return;
    }
  }

  const statusId = mode === 'today' ? 'load-status-today' : 'load-status-tomorrow';
  const loadStatus = document.getElementById(statusId);
  loadStatus.textContent = 'Loading...';

  const endpoint = mode === 'today' ? '/load-today-from-master' : '/preload-from-master';
  const payload = targetDate ? { target_date: targetDate } : null;
  if (payload && mode !== 'today') {
    payload.force_csv = forceCsv;
  }

  try {
    const response = await fetch(endpoint, {
      method: 'POST',
      headers: payload ? { 'Content-Type': 'application/json' } : undefined,
      body: payload ? JSON.stringify(payload) : undefined,
    });
    const result = await response.json();

  if (response.ok) {
      updatePrepLoadResultLabel(result.message || 'Loaded!', 'success', mode === 'today' ? 'today' : 'tomorrow');
      if (mode === 'next' && result.target_date) {
        setPrepTargetMeta({ dateValue: result.target_date });
        updatePrepTargetUI();
      }
      await loadData();
    } else {
      updatePrepLoadResultLabel(result.error || 'Error', 'error', mode === 'today' ? 'today' : 'tomorrow');
    }
  } catch (error) {
    updatePrepLoadResultLabel('Error: ' + error.message, 'error', mode === 'today' ? 'today' : 'tomorrow');
  }
}

// Show message (XSS-safe)
function showMessage(type, message) {
  const container = document.getElementById('message-container');
  const div = document.createElement('div');
  div.className = `message ${type}`;
  div.textContent = message;  // textContent is XSS-safe
  container.innerHTML = '';
  container.appendChild(div);
  setTimeout(() => { container.innerHTML = ''; }, 5000);
}

// Initialize edit mode UI and load current tab (lazy loading)
applyEditModeUI(currentTab);
loadTabData(currentTab);
if (currentTab === 'today') {
  togglePrepAutoRefresh('today');
}
