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
  const times = taskConfig.times || {};
  const dayTimes = typeof resolveDayTimes === 'function'
    ? resolveDayTimes(times, targetDay)
    : (times[targetDay] || times.default);
  if (Array.isArray(dayTimes)) {
    return parseDayTimes(dayTimes[0]);
  }
  return parseDayTimes(dayTimes);
}

// Toggle inline edit mode
async function toggleEditMode(tab) {
  const wasActive = editMode[tab];
  editMode[tab] = !editMode[tab];
  pendingChanges[tab] = {};  // Reset pending changes
  applyEditModeUI(tab);
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
      pendingChanges[tab][key] = { modality: modKey, row_index: -1, groupIdx, shiftIdx, isNew: true, updates: {} };
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
      pendingChanges[tab][key] = { modality: modKey, row_index: -1, groupIdx, shiftIdx, isNew: true, updates: {} };
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
const VALID_MODIFIER_VALUES = [0.3, 0.5, 0.75, 1, 1.0, 1.25, 1.5];

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
  const color = getSkillColor(normalized);
  el.style.backgroundColor = color + '20';
  el.style.borderColor = color;

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
  else if (parsed > 1.5) parsed = 1.5;

  // Round to nearest valid value
  const validValues = [0.3, 0.5, 0.75, 1.0, 1.25, 1.5];
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
  else if (parsed > 1.5) parsed = 1.5;

  // Round to nearest valid value
  const validValues = [0.3, 0.5, 0.75, 1.0, 1.25, 1.5];
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
    const validValues = [0.3, 0.5, 0.75, 1.0, 1.25, 1.5];
    const idx = validValues.indexOf(val);
    const next = idx < validValues.length - 1 ? validValues[idx + 1] : validValues[validValues.length - 1];
    el.value = next;
    saveFunction(el);
    event.preventDefault();
  } else if (event.key === 'ArrowDown') {
    const val = parseFloat(el.value) || 1.0;
    const validValues = [0.3, 0.5, 0.75, 1.0, 1.25, 1.5];
    const idx = validValues.indexOf(val);
    const next = idx > 0 ? validValues[idx - 1] : validValues[0];
    el.value = next;
    saveFunction(el);
    event.preventDefault();
  }
}

// Save all inline changes (handles both updates and new modality additions)
async function saveInlineChanges(tab) {
  const changes = Object.values(pendingChanges[tab]);
  if (changes.length === 0) {
    showMessage('error', 'No changes to save');
    return;
  }

  const updateEndpoint = tab === 'today' ? '/api/live-schedule/update-row' : '/api/prep-next-day/update-row';
  const addEndpoint = tab === 'today' ? '/api/live-schedule/add-worker' : '/api/prep-next-day/add-worker';
  const deleteEndpoint = tab === 'today' ? '/api/live-schedule/delete-worker' : '/api/prep-next-day/delete-worker';

  // Collect errors instead of throwing on first failure
  const errors = [];
  let successCount = 0;

  for (const change of changes) {
    try {
      if (change.isDelete) {
        const response = await fetch(deleteEndpoint, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            modality: change.modality,
            row_index: change.row_index,
            verify_ppl: change.verify_ppl
          })
        });

        if (!response.ok) {
          const result = await response.json().catch(() => ({}));
          errors.push(`Delete ${change.modality}: ${result.error || 'Unknown error'}`);
        } else {
          successCount++;
        }
      } else if (change.isNew) {
        // New modality addition - need to add via add-worker endpoint
        const group = entriesData[tab][change.groupIdx];
        const shift = group ? getTableShifts(group)[change.shiftIdx] : null;
        if (!group || !shift) continue;

        // Only add if any skill is set to 0/1/w (skip pure -1 placeholders)
        const hasActiveSkill = SKILLS.some(skill => {
          const val = change.updates[skill];
          return val !== undefined && isNonNegativeSkillValue(val);
        });
        if (!hasActiveSkill) continue;

        // Build worker_data for the new modality
        const workerData = {
          PPL: group.worker,
          start_time: shift.start_time,
          end_time: shift.end_time,
          Modifier: change.updates.Modifier || 1.0,
          tasks: shift.task || ''
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

        const response = await fetch(addEndpoint, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ modality: change.modality, worker_data: workerData })
        });

        if (!response.ok) {
          const result = await response.json().catch(() => ({}));
          errors.push(`Add ${change.modality}: ${result.error || 'Unknown error'}`);
        } else {
          successCount++;
        }
      } else {
        // Existing entry update
        const response = await fetch(updateEndpoint, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(change)
        });

        if (!response.ok) {
          const result = await response.json().catch(() => ({}));
          errors.push(`Update ${change.modality}: ${result.error || 'Unknown error'}`);
        } else {
          successCount++;
        }
      }
    } catch (fetchError) {
      errors.push(`Network error: ${fetchError.message}`);
    }
  }

  // Show appropriate message based on results
  if (errors.length === 0) {
    showMessage('success', `Saved ${successCount} change${successCount !== 1 ? 's' : ''}`);
  } else if (successCount > 0) {
    showMessage('error', `Saved ${successCount}, failed ${errors.length}: ${errors[0]}`);
  } else {
    showMessage('error', `All ${errors.length} changes failed: ${errors[0]}`);
  }

  pendingChanges[tab] = {};
  applyEditModeUI(tab);
  await loadData();
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

function isTabAvailable(tab) {
  return Boolean(document.getElementById(`content-${tab}`));
}

function updatePrepTargetUI() {
  const labelEl = document.getElementById('prep-target-date-label');
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
}

function onPrepDateInputChange() {
  const inputEl = document.getElementById('prep-target-date');
  if (!inputEl) return;
  const value = inputEl.value;
  if (!value) return;
  if (prepMinDate && value < prepMinDate) {
    showMessage('error', `Prep-Datum muss ab ${prepMinDate} liegen.`);
    inputEl.value = prepMinDate;
    setPrepTargetMeta({ dateValue: prepMinDate });
    updatePrepTargetUI();
    return;
  }
  setPrepTargetMeta({ dateValue: value });
  updatePrepTargetUI();
}

// Load data for a specific tab (lazy loading)
async function loadTabData(tab) {
  if (!isTabAvailable(tab)) {
    return;
  }
  const requestId = ++loadRequestId[tab];
  try {
    const endpoint = tab === 'today' ? '/api/live-schedule/data' : '/api/prep-next-day/data';
    const response = await fetch(endpoint);

    if (requestId !== loadRequestId[tab]) {
      return;
    }
    if (!response.ok) {
      const text = await response.text();
      console.error(`${tab} API error:`, text);
      if (requestId === loadRequestId[tab]) {
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
      if (requestId === loadRequestId[tab]) {
        rawData[tab] = {};
        dataLoaded[tab] = false;
      }
      return;
    }

    if (requestId !== loadRequestId[tab]) {
      return;
    }
    const result = buildEntriesByWorker(respData.modalities || respData, tab);
    entriesData[tab] = result.entries;
    workerCounts[tab] = result.counts;
    dataLoaded[tab] = true;

    if (tab === 'tomorrow') {
      if (respData.target_date || respData.target_weekday_name) {
        setPrepTargetMeta({
          dateValue: respData.target_date,
          weekdayName: respData.target_weekday_name,
        });
        updatePrepTargetUI();
      }
      const infoEl = document.getElementById('last-prepped-info');
      if (respData.last_prepped_at) {
        if (infoEl) infoEl.innerHTML = `Vorbereitet am: <strong>${respData.last_prepped_at}</strong>`;
      } else if (infoEl) {
        infoEl.textContent = 'Noch nicht vorbereitet';
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
  if (!confirm(`Delete all ${allEntries.length} entries for ${group.worker}?`)) return;

  const endpoint = tab === 'today' ? '/api/live-schedule/delete-worker' : '/api/prep-next-day/delete-worker';

  try {
    // Delete all entries in reverse order (to avoid index shifting issues)
    // Sort by row_index descending to delete from end first
    const sortedEntries = [...allEntries].sort((a, b) => b.row_index - a.row_index);
    for (const entry of sortedEntries) {
      const response = await fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ modality: entry.modality, row_index: entry.row_index, verify_ppl: entry.worker })
      });
      if (!response.ok) {
        const errData = await response.json().catch(() => ({}));
        throw new Error(errData.error || `Failed to delete ${entry.modality} entry for ${entry.worker}`);
      }
    }
    showMessage('success', `Deleted all entries for ${group.worker}`);
    await loadData();
  } catch (error) {
    showMessage('error', error.message);
  }
}

// Delete single entry
async function deleteEntry(tab, groupIdx, entryIdx) {
  const group = entriesData[tab][groupIdx];
  if (!group) return;
  const entry = group.entries[entryIdx];
  if (!entry) return;

  if (!confirm(`Delete entry for ${entry.worker} (${entry.modality.toUpperCase()} ${entry.start_time}-${entry.end_time})?`)) return;

  const endpoint = tab === 'today' ? '/api/live-schedule/delete-worker' : '/api/prep-next-day/delete-worker';

  try {
    const response = await fetch(endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ modality: entry.modality, row_index: entry.row_index, verify_ppl: entry.worker })
    });
    if (!response.ok) {
      const errData = await response.json().catch(() => ({}));
      throw new Error(errData.error || `Failed to delete entry for ${entry.worker}`);
    }
    showMessage('success', `Deleted entry for ${entry.worker}`);
    await loadData();
  } catch (error) {
    showMessage('error', error.message);
  }
}

// Open Edit modal for a worker - edit skills per modality
function openEditModal(tab, groupIdx) {
  const group = entriesData[tab][groupIdx];
  if (!group) return;

  currentEditEntry = { tab, groupIdx };
  setEditPlanDraftFromGroup(group, { force: true });
  setModalMode('edit-plan');
  modalEditMode = true;
  renderEditModalContent();
  document.getElementById('edit-modal').classList.add('show');
}

// Handle task change in existing shift (edit modal) - live update
async function onEditShiftTaskChange(shiftIdx, taskName) {
  const taskConfig = TASK_ROLES.find(t => t.name === taskName);
  if (!taskConfig) return;

  const isGap = taskConfig.type === 'gap';
  const { tab, groupIdx } = currentEditEntry || {};

  // Prepare updates for API call
  const updates = { tasks: taskName };
  const skillUpdates = {};

  if (isGap) {
    // Gap selected - set all skills to -1 and use times for target day
    const targetDay = getTargetWeekdayName(tab || currentTab);
    const parsedTimes = getGapTimeRange(taskConfig, targetDay);
    if (parsedTimes) {
      const [startTime, endTime] = parsedTimes;
      updates.start_time = startTime;
      updates.end_time = endTime;
      const startEl = document.getElementById(`edit-shift-${shiftIdx}-start`);
      const endEl = document.getElementById(`edit-shift-${shiftIdx}-end`);
      if (startEl) startEl.value = startTime;
      if (endEl) endEl.value = endTime;
    }
    updates.Modifier = 1.0;
    updates.row_type = 'gap';
    updates.counts_for_hours = getGapCountsForHours(taskName);
    const modifierEl = document.getElementById(`edit-shift-${shiftIdx}-modifier`);
    if (modifierEl) modifierEl.value = '1.0';
    const countsEl = document.getElementById(`edit-shift-${shiftIdx}-counts-hours`);
    if (countsEl) {
      countsEl.checked = updates.counts_for_hours === true;
      updateHoursToggleLabel(countsEl);
    }

    // Set ALL skills to -1 for gaps across modalities
    MODALITIES.forEach(mod => {
      const modKey = mod.toLowerCase();
      SKILLS.forEach(skill => {
        const skillSelect = document.getElementById(`edit-shift-${shiftIdx}-${modKey}-skill-${skill}`);
        if (skillSelect) skillSelect.value = '-1';
        if (!skillUpdates[modKey]) skillUpdates[modKey] = {};
        skillUpdates[modKey][skill] = -1;
      });
    });
  } else {
    // Regular shift selected - preload skills from task's skill_overrides (like CSV loading)
    const targetDay = getTargetWeekdayName(tab || currentTab);
    const times = getShiftTimes(taskConfig, targetDay);
    updates.start_time = times.start;
    updates.end_time = times.end;
    updates.row_type = 'shift';
    const startEl = document.getElementById(`edit-shift-${shiftIdx}-start`);
    const endEl = document.getElementById(`edit-shift-${shiftIdx}-end`);
    if (startEl) startEl.value = times.start;
    if (endEl) endEl.value = times.end;

    if (taskConfig.modifier) {
      updates.Modifier = taskConfig.modifier;
    }
    const modifierEl = document.getElementById(`edit-shift-${shiftIdx}-modifier`);
    if (modifierEl && taskConfig.modifier) modifierEl.value = taskConfig.modifier.toString();

    // Also update counts_for_hours based on task config
    updates.counts_for_hours = taskConfig.counts_for_hours !== false;
    const countsEl = document.getElementById(`edit-shift-${shiftIdx}-counts-hours`);
    if (countsEl) {
      countsEl.checked = taskConfig.counts_for_hours !== false;
      updateHoursToggleLabel(countsEl);
    }

    // Preload skills from task's skill_overrides (supports "Skill_modality" format like CSV loading)
    const overrides = taskConfig.skill_overrides || {};
    MODALITIES.forEach(mod => {
      const modKey = mod.toLowerCase();
      if (!skillUpdates[modKey]) skillUpdates[modKey] = {};
      SKILLS.forEach(skill => {
        const skillSelect = document.getElementById(`edit-shift-${shiftIdx}-${modKey}-skill-${skill}`);
        // Check for skill_modality format (e.g., "notfall_ct") first, then skill-only
        const skillModKey = `${skill}_${modKey}`;
        let val = 0;  // Default to passive
        if (overrides[skillModKey] !== undefined) {
          val = overrides[skillModKey];
        } else if (overrides[skill] !== undefined) {
          val = overrides[skill];
        } else if (overrides['all'] !== undefined) {
          val = overrides['all'];
        }
        if (skillSelect) {
          skillSelect.value = val.toString();
        }
        skillUpdates[modKey][skill] = normalizeSkillValueJS(val);
      });
    });

    // Apply worker roster exclusions (-1) - roster -1 always wins
    // Roster structure is modality-scoped: { modality: { skill: value } }
    const group = entriesData[tab]?.[groupIdx];
    if (group) {
      const workerRoster = WORKER_SKILLS[group.worker];
      if (workerRoster) {
        MODALITIES.forEach(mod => {
          const modKey = mod.toLowerCase();
          const modalityRoster = workerRoster[modKey] || {};
          SKILLS.forEach(skill => {
            const skillSelect = document.getElementById(`edit-shift-${shiftIdx}-${modKey}-skill-${skill}`);
            if (modalityRoster[skill] === -1) {
              if (skillSelect) skillSelect.value = '-1';
              skillUpdates[modKey][skill] = -1;  // Roster -1 always wins
            }
          });
        });
      }
    }
  }

  updateEditPlanDraftShift(shiftIdx, updates);
  updateEditPlanDraftShiftSkills(shiftIdx, skillUpdates);
  if (modalMode === 'edit-plan') {
    // All DOM updates already done above - no need for full re-render
    // Just update the visual GAP indicator if row type changed
    const shiftContainer = document.getElementById(`edit-shift-${shiftIdx}-task`)?.closest('[style*="margin-bottom: 1rem"]');
    if (shiftContainer) {
      const headerSpan = shiftContainer.querySelector('span[style*="font-weight: 600"]');
      if (headerSpan) {
        const isGap = updates.row_type === 'gap';
        const gapBadge = isGap ? ' <span style="background:#f8d7da;color:#721c24;padding:0.1rem 0.3rem;border-radius:3px;font-size:0.7rem;">GAP</span>' : '';
        headerSpan.innerHTML = `Shift ${shiftIdx + 1}${gapBadge}`;
      }
    }
    return;
  }

  // Live save to backend
  const group = entriesData[tab]?.[groupIdx];
  if (!group) return;
  const shifts = getModalShifts(group);
  const shift = shifts[shiftIdx];
  if (!shift) return;

  const endpoint = tab === 'today' ? '/api/live-schedule/update-row' : '/api/prep-next-day/update-row';

  try {
    let anySuccess = false;
    for (const [modKey, modData] of Object.entries(shift.modalities)) {
      if (modData.row_index !== undefined && modData.row_index >= 0) {
        // Combine base updates with modality-specific skill updates
        const modUpdates = { ...updates };
        if (skillUpdates[modKey]) {
          Object.assign(modUpdates, skillUpdates[modKey]);
        }
        const response = await fetch(endpoint, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            modality: modKey,
            row_index: modData.row_index,
            updates: modUpdates
          })
        });
        if (response.ok) {
          anySuccess = true;
        }
      }
    }
    if (anySuccess) {
      // Preserve form state before re-render
      const formState = saveModalAddFormState();
      const workerName = group.worker;
      await loadData();
      reopenEditModalForWorker(tab, workerName, formState);
    } else {
      showMessage('error', 'Failed to update task');
    }
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
  const confirmMessage = isLastShift
    ? `Delete this shift (${shift.start_time}-${shift.end_time})? This is the last shift for ${group.worker}, so the worker will be removed. Continue?`
    : `Delete this shift (${shift.start_time}-${shift.end_time})?`;

  if (!confirm(confirmMessage)) return;

  if (modalMode === 'edit-plan') {
    const updatedShifts = [...shifts];
    updatedShifts.splice(shiftIdx, 1);
    if (editPlanDraft) {
      editPlanDraft.shifts = updatedShifts;
    }
    renderEditModalContent();
    return;
  }

  const endpoint = tab === 'today' ? '/api/live-schedule/apply-worker-plan' : '/api/prep-next-day/apply-worker-plan';
  const workerName = group.worker;

  try {
    const updatedShifts = [...shifts];
    updatedShifts.splice(shiftIdx, 1);
    if (editPlanDraft) {
      editPlanDraft.shifts = updatedShifts;
    }
    const response = await fetch(endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ worker: group.worker, shifts: updatedShifts })
    });
    if (!response.ok) {
      const errData = await response.json().catch(() => ({}));
      throw new Error(errData.error || 'Failed to delete shift');
    }
    showMessage('success', 'Shift deleted');

    if (isLastShift) {
      // Worker removed - close modal
      closeModal();
      await loadData();
    } else {
      // More shifts remain - reload and re-render modal
      const formState = saveModalAddFormState();
      await loadData();
      const updatedGroupIdx = entriesData[tab]?.findIndex(entry => entry.worker === workerName);
      if (updatedGroupIdx !== undefined && updatedGroupIdx >= 0) {
        currentEditEntry = { tab, groupIdx: updatedGroupIdx };
        renderEditModalContent();
        restoreModalAddFormState(formState);
        return;
      }
      // Worker no longer exists (edge case) - close modal
      closeModal();
    }
  } catch (error) {
    showMessage('error', error.message);
  }
}



// Live update shift fields from edit modal (no Save button needed)
async function updateShiftFromModal(shiftIdx, updates) {
  const { tab, groupIdx } = currentEditEntry || {};
  const group = entriesData[tab]?.[groupIdx];
  if (!group) return;

  const shifts = getModalShifts(group);
  const shift = shifts[shiftIdx];
  if (!shift) return;

  const endpoint = tab === 'today' ? '/api/live-schedule/update-row' : '/api/prep-next-day/update-row';

  try {
    let anySuccess = false;
    updateEditPlanDraftShift(shiftIdx, updates);
    if (modalMode === 'edit-plan') return;
    for (const [modKey, modData] of Object.entries(shift.modalities)) {
      if (modData.row_index !== undefined && modData.row_index >= 0) {
        const response = await fetch(endpoint, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            modality: modKey,
            row_index: modData.row_index,
            updates
          })
        });
        if (response.ok) {
          anySuccess = true;
        }
      }
    }
    if (anySuccess) {
      // Preserve form state before re-render
      const formState = saveModalAddFormState();
      const workerName = group.worker;
      const modalState = captureModalState();
      await loadData();
      if (reopenEditModalForWorker(tab, workerName, formState)) {
        restoreModalState(modalState);
      }
    } else {
      showMessage('error', 'Failed to update shift');
    }
  } catch (error) {
    showMessage('error', error.message);
  }
}

// Live update a single skill from edit modal
async function updateShiftSkillFromModal(shiftIdx, modKey, skill, value) {
  const { tab, groupIdx } = currentEditEntry || {};
  const group = entriesData[tab]?.[groupIdx];
  if (!group) return;

  const shifts = getModalShifts(group);
  const shift = shifts[shiftIdx];
  if (!shift) return;

  const modData = shift.modalities[modKey];
  if (!modData || modData.row_index === undefined || modData.row_index < 0) return;

  const endpoint = tab === 'today' ? '/api/live-schedule/update-row' : '/api/prep-next-day/update-row';

  try {
    const skillUpdates = {};
    const normalizedValue = normalizeSkillValueJS(value);
    skillUpdates[skill] = normalizedValue;
    updateEditPlanDraftShiftSkills(shiftIdx, { [modKey]: { [skill]: normalizedValue } });
    if (modalMode === 'edit-plan') return;

    const response = await fetch(endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        modality: modKey,
        row_index: modData.row_index,
        updates: skillUpdates
      })
    });

    if (!response.ok) {
      showMessage('error', `Failed to update ${skill} skill`);
    }
    // No re-render needed for skill changes - they're local to the row
  } catch (error) {
    showMessage('error', error.message);
  }
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
  currentEditEntry = { tab, groupIdx: updatedGroupIdx };
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
function onModalTaskChange() {
  const taskSelect = document.getElementById('modal-add-task');
  const option = taskSelect?.options[taskSelect.selectedIndex];
  if (!option || !option.value) {
    return;
  }

  const taskName = option.value;
  const taskConfig = TASK_ROLES.find(t => t.name === taskName);
  const isGap = option.dataset.type === 'gap';
  const { tab, groupIdx } = currentEditEntry || {};

  // Set times - use target day based on current tab (today vs tomorrow)
  if (isGap) {
    const targetDay = getTargetWeekdayName(tab || currentTab);
    const parsedTimes = getGapTimeRange(taskConfig, targetDay);
    const [startTime, endTime] = parsedTimes || ['12:00', '13:00'];
    document.getElementById('modal-add-start').value = startTime;
    document.getElementById('modal-add-end').value = endTime;
  } else if (!isGap && taskConfig) {
    // Use day-specific times from task config
    const targetDay = getTargetWeekdayName(tab || currentTab);
    const times = getShiftTimes(taskConfig, targetDay);
    document.getElementById('modal-add-start').value = times.start;
    document.getElementById('modal-add-end').value = times.end;
  } else {
    // Fallback defaults
    const defaultTime = isGap ? '12:00-13:00' : '07:00-15:00';
    const [startTime, endTime] = defaultTime.split('-');
    document.getElementById('modal-add-start').value = startTime;
    document.getElementById('modal-add-end').value = endTime;
  }

  // Set modifier from task config
  const modifier = option.dataset.modifier || '1.0';
  document.getElementById('modal-add-modifier').value = modifier;

  // Update hours count checkbox based on task type
  const countsEl = document.getElementById('modal-add-counts-hours');
  if (countsEl) {
    countsEl.checked = taskConfig?.counts_for_hours !== false;
    updateHoursToggleLabel(countsEl);
  }

  // Preload skills from task's skill_overrides (supports "Skill_modality" format like CSV loading)
  const overrides = taskConfig?.skill_overrides || {};

  MODALITIES.forEach(mod => {
    const modKey = mod.toLowerCase();
    SKILLS.forEach(skill => {
      const el = document.getElementById(`modal-add-${modKey}-skill-${skill}`);
      if (!el) return;

      if (isGap) {
        el.value = '-1';  // All skills excluded for gaps
      } else {
        // Check for skill_modality format (e.g., "notfall_ct") first, then skill-only
        const skillModKey = `${skill}_${modKey}`;
        let val = 0;  // Default to passive
        if (overrides[skillModKey] !== undefined) {
          val = overrides[skillModKey];
        } else if (overrides[skill] !== undefined) {
          val = overrides[skill];
        } else if (overrides['all'] !== undefined) {
          val = overrides['all'];
        }
        el.value = val.toString();
      }
    });
  });

  // Apply worker roster exclusions (-1) - roster -1 always wins
  // Roster structure is modality-scoped: { modality: { skill: value } }
  const group = entriesData[tab]?.[groupIdx];
  if (group) {
    const workerRoster = WORKER_SKILLS[group.worker];
    if (workerRoster) {
      MODALITIES.forEach(mod => {
        const modKey = mod.toLowerCase();
        const modalityRoster = workerRoster[modKey] || {};
        SKILLS.forEach(skill => {
          const el = document.getElementById(`modal-add-${modKey}-skill-${skill}`);
          if (el && modalityRoster[skill] === -1) {
            el.value = '-1';  // Roster -1 always wins
          }
        });
      });
    }
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

  // Save skill values for all modalities
  formState.skills = {};
  MODALITIES.forEach(mod => {
    const modKey = mod.toLowerCase();
    formState.skills[modKey] = {};
    SKILLS.forEach(skill => {
      const el = document.getElementById(`modal-add-${modKey}-skill-${skill}`);
      if (el) formState.skills[modKey][skill] = el.value;
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

  // Restore skill values
  if (formState.skills) {
    MODALITIES.forEach(mod => {
      const modKey = mod.toLowerCase();
      const modSkills = formState.skills[modKey] || {};
      SKILLS.forEach(skill => {
        const el = document.getElementById(`modal-add-${modKey}-skill-${skill}`);
        if (el && modSkills[skill] !== undefined) el.value = modSkills[skill];
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
          el.value = val.toString();
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
  const taskKey = (taskName || '').trim();
  const addedShiftKey = `${startTime}-${endTime}-${isGap ? 'gap' : 'shift'}-${taskKey}`;

  if (modalMode === 'edit-plan') {
    if (!editPlanDraft) {
      showMessage('error', 'No edit plan available');
      return;
    }
    const modalities = {};
    selectedModalities.forEach(modKey => {
      const skills = {};
      SKILLS.forEach(skill => {
        if (isGap) {
          skills[skill] = -1;
          return;
        }
        const el = document.getElementById(`modal-add-${modKey}-skill-${skill}`);
        skills[skill] = normalizeSkillValueJS(el ? el.value : 0);
      });
      modalities[modKey] = {
        skills,
        row_index: -1,
        modifier
      };
    });

    editPlanDraft.shifts = [
      ...(editPlanDraft.shifts || []),
      {
        start_time: startTime,
        end_time: endTime,
        modifier,
        counts_for_hours: countsForHours,
        task: taskName,
        row_type: isGap ? 'gap' : 'shift',
        is_gap_entry: isGap,
        modalities,
        timeSegments: [{ start: startTime, end: endTime }],
      }
    ];
    showMessage('success', `Added new ${isGap ? 'gap' : 'shift'} for ${group.worker}. Save edits to apply.`);
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

      const gapPayloads = Array.from(rowIndexByModality.entries()).map(([modality, rowIndex]) => (
        fetch(addGapEndpoint, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            modality,
            row_index: rowIndex,
            gap_type: taskName,
            gap_start: startTime,
            gap_end: endTime,
            gap_counts_for_hours: countsForHours
          })
        })
      ));
      const responses = await Promise.all(gapPayloads);
      const failedResponse = responses.find(response => !response.ok);
      if (failedResponse) {
        const errData = await failedResponse.json().catch(() => ({}));
        throw new Error(errData.error || `Failed to add gap for ${group.worker}`);
      }
    } else {
      for (const modKey of selectedModalities) {
        const skills = {};
        SKILLS.forEach(skill => {
          const el = document.getElementById(`modal-add-${modKey}-skill-${skill}`);
          skills[skill] = normalizeSkillValueJS(el ? el.value : 0);
        });
        const response = await fetch(addWorkerEndpoint, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            modality: modKey,
            worker_data: {
              PPL: group.worker,
              start_time: startTime,
              end_time: endTime,
              Modifier: modifier,
              counts_for_hours: countsForHours,
              tasks: taskName,
              row_type: 'shift',
              ...skills
            }
          })
        });

        if (!response.ok) {
          const errData = await response.json().catch(() => ({}));
          throw new Error(errData.error || `Failed to add shift for ${modKey.toUpperCase()}`);
        }
      }
    }
    showMessage('success', `Added new ${isGap ? 'gap' : 'shift'} for ${group.worker}`);

    lastAddedShiftMeta = { worker: group.worker, shiftKey: addedShiftKey };
    await loadData();
    // Re-render modal to show updated shifts instead of closing
    renderEditModalContent();
  } catch (error) {
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
    showMessage('error', `No skill preset found for ${workerName}`);
    return;
  }

  // Roster structure is modality-scoped: { modality: { skill: value } }
  const modalitySkills = workerRoster[modKey] || {};

  SKILLS.forEach(skill => {
    const el = document.getElementById(`edit-${modKey}-skill-${skill}`);
    if (el && modalitySkills[skill] !== undefined) {
      // Limit roster presets to 0/-1; positive values are reserved for manual/CSV edits
      const val = modalitySkills[skill];
      el.value = (val > 0 ? 0 : val).toString();
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
    showMessage('error', `No skill preset found for ${workerName || 'worker'}`);
    return;
  }

  // Roster structure is modality-scoped: { modality: { skill: value } }
  const modalitySkills = workerRoster[modKey] || {};

  SKILLS.forEach(skill => {
    const el = document.getElementById(`edit-shift-${shiftIdx}-${modKey}-skill-${skill}`);
    if (el && modalitySkills[skill] !== undefined) {
      // Limit roster presets to 0/-1; positive values are reserved for manual/CSV edits
      const val = modalitySkills[skill];
      el.value = (val > 0 ? 0 : val).toString();
    }
  });
}

// Apply preset from config to all modalities in a shift
function applyPresetToShift(shiftIdx, taskName) {
  if (!taskName) return;

  const task = TASK_ROLES.find(t => t.name === taskName);
  if (!task) {
    showMessage('error', `Preset not found: ${taskName}`);
    return;
  }

  const overrides = task.skill_overrides || {};
  const { tab, groupIdx } = currentEditEntry || {};
  const group = entriesData[tab]?.[groupIdx];
  if (!group) return;

  const shift = getModalShifts(group)[shiftIdx];
  if (!shift) return;

  // Apply skills to all modalities in this shift
  // Config uses skill×modality format: { "notfall_ct": 1, "privat_mr": 0 }
  // Also supports shortcuts: { "all": -1 }, { "mdh": 1 }
  Object.keys(shift.modalities).forEach(modKey => {
    SKILLS.forEach(skill => {
      const el = document.getElementById(`edit-shift-${shiftIdx}-${modKey}-skill-${skill}`);
      if (el) {
        // Check skill×modality format first, then skill shortcut, then "all" shortcut
        const skillModKey = `${skill}_${modKey}`;
        let val = 0;  // Default to passive
        if (overrides[skillModKey] !== undefined) {
          val = overrides[skillModKey];
        } else if (overrides[skill] !== undefined) {
          val = overrides[skill];  // Skill shortcut applies to all modalities
        } else if (overrides['all'] !== undefined) {
          val = overrides['all'];
        }
        el.value = val.toString();
      }
    });
  });

  // Apply shift load modifier if task config provides one.
  if (task.modifier !== undefined) {
    const modifierEl = document.getElementById(`edit-shift-${shiftIdx}-modifier`);
    if (modifierEl) {
      modifierEl.value = task.modifier.toString();
    }
  }

  // Update shift times from task config (day-specific)
  const targetDay = getTargetWeekdayName(tab || currentTab);
  const times = getShiftTimes(task, targetDay);

  const startEl = document.getElementById(`edit-shift-${shiftIdx}-start`);
  const endEl = document.getElementById(`edit-shift-${shiftIdx}-end`);
  if (startEl) startEl.value = times.start;
  if (endEl) endEl.value = times.end;
}

// Apply worker roster skills to all modalities in a shift
function applyWorkerRosterToShift(shiftIdx) {
  const { tab, groupIdx } = currentEditEntry || {};
  const group = entriesData[tab]?.[groupIdx];
  if (!group) return;

  const workerRoster = WORKER_SKILLS[group.worker];
  if (!workerRoster) {
    showMessage('error', `No skill preset found for ${group.worker}`);
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
        el.value = (val > 0 ? 0 : val).toString();
      }
    });
  });
}

async function saveModalChanges() {
  if (!currentEditEntry) return;

  const { tab, groupIdx } = currentEditEntry;
  const group = entriesData[tab][groupIdx];
  if (!group) return;

  const updateEndpoint = tab === 'today' ? '/api/live-schedule/update-row' : '/api/prep-next-day/update-row';
  const shifts = getModalShifts(group);

  if (modalMode === 'edit-plan') {
    if (!modalEditMode) {
      showMessage('error', 'Enable Edit Mode to save changes.');
      return;
    }
    if (!editPlanDraft || !editPlanDraft.worker) {
      showMessage('error', 'No edit plan available');
      return;
    }
    const applyEndpoint = tab === 'today'
      ? '/api/live-schedule/apply-worker-plan'
      : '/api/prep-next-day/apply-worker-plan';
    try {
      syncEditPlanDraftFromModal();
      const response = await fetch(applyEndpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ worker: editPlanDraft.worker, shifts: editPlanDraft.shifts || [] })
      });
      if (!response.ok) {
        const result = await response.json();
        throw new Error(result.error || 'Failed to apply worker plan');
      }
      clearEditPlanDraft();
      closeModal();
      showMessage('success', 'Worker entries updated');
      await loadData();
      return;
    } catch (error) {
      showMessage('error', error.message);
      return;
    }
  }

  try {
    for (let shiftIdx = 0; shiftIdx < shifts.length; shiftIdx++) {
      const shift = shifts[shiftIdx];

      const shiftTaskEl = document.getElementById(`edit-shift-${shiftIdx}-task`);
      const shiftStartEl = document.getElementById(`edit-shift-${shiftIdx}-start`);
      const shiftEndEl = document.getElementById(`edit-shift-${shiftIdx}-end`);
      const shiftModifierEl = document.getElementById(`edit-shift-${shiftIdx}-modifier`);

      const shiftTask = shiftTaskEl ? shiftTaskEl.value : shift.task;
      const shiftStart = shiftStartEl ? shiftStartEl.value : shift.start_time;
      const shiftEnd = shiftEndEl ? shiftEndEl.value : shift.end_time;
      const shiftModifier = shiftModifierEl ? parseFloat(shiftModifierEl.value) || 1.0 : shift.modifier || 1.0;

      // Get counts_for_hours checkbox value
      const countsHoursEl = document.getElementById(`edit-shift-${shiftIdx}-counts-hours`);
      const countsForHours = countsHoursEl ? countsHoursEl.checked : (shift.counts_for_hours !== false);

      for (const [modKey, modData] of Object.entries(shift.modalities)) {
        const rowIndexEl = document.getElementById(`edit-shift-${shiftIdx}-${modKey}-rowindex`);
        const rowIndex = rowIndexEl ? parseInt(rowIndexEl.value) : modData.row_index;

        // Only update existing entries (rowIndex >= 0)
        // Modal no longer has modality enable/disable checkboxes
        if (rowIndex < 0) continue;

        const skillUpdates = {};
        SKILLS.forEach(skill => {
          const el = document.getElementById(`edit-shift-${shiftIdx}-${modKey}-skill-${skill}`);
          if (el) {
            skillUpdates[skill] = normalizeSkillValueJS(el.value);
          }
        });

        const updates = {
          start_time: shiftStart,
          end_time: shiftEnd,
          Modifier: shiftModifier,
          counts_for_hours: countsForHours,
          tasks: shiftTask,
          ...skillUpdates
        };
        const response = await fetch(updateEndpoint, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ modality: modKey, row_index: rowIndex, updates })
        });
        if (!response.ok) {
          const result = await response.json();
          throw new Error(result.error || `Failed to update ${modKey.toUpperCase()} entry`);
        }
      }
    }

    closeModal();
    showMessage('success', 'Worker entries updated');
    await loadData();
  } catch (error) {
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
    const updates = {};
    const taskEl = document.getElementById(`edit-shift-${shiftIdx}-task`);
    if (taskEl && taskEl.value) updates.tasks = taskEl.value;
    const startEl = document.getElementById(`edit-shift-${shiftIdx}-start`);
    if (startEl && isValidTimeValue(startEl.value)) updates.start_time = startEl.value;
    const endEl = document.getElementById(`edit-shift-${shiftIdx}-end`);
    if (endEl && isValidTimeValue(endEl.value)) updates.end_time = endEl.value;
    const modifierEl = document.getElementById(`edit-shift-${shiftIdx}-modifier`);
    if (modifierEl) updates.Modifier = parseFloat(modifierEl.value) || 1.0;
    const countsEl = document.getElementById(`edit-shift-${shiftIdx}-counts-hours`);
    if (countsEl) updates.counts_for_hours = countsEl.checked;
    if (Object.keys(updates).length) {
      updateEditPlanDraftShift(shiftIdx, updates);
    }

    const skillUpdatesByMod = {};
    Object.keys(shift.modalities || {}).forEach(modKey => {
      SKILLS.forEach(skill => {
        const el = document.getElementById(`edit-shift-${shiftIdx}-${modKey}-skill-${skill}`);
        if (el) {
          if (!skillUpdatesByMod[modKey]) skillUpdatesByMod[modKey] = {};
          skillUpdatesByMod[modKey][skill] = normalizeSkillValueJS(el.value);
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
  modalEditMode = true;
  setModalMode('edit');
}

function setModalMode(mode) {
  modalMode = mode;
  const saveButton = document.getElementById('modal-save-button');
  if (!saveButton) return;
  if (mode === 'add-worker') {
    saveButton.textContent = 'Add Worker';
    saveButton.className = 'btn btn-success';
  } else if (mode === 'edit-plan') {
    saveButton.textContent = 'Save Edits';
    saveButton.className = 'btn btn-primary';
  } else {
    // Edit mode: all edits are live, no Save button needed
    saveButton.style.display = 'none';
  }
  applyModalEditModeUI();
}

function applyModalEditModeUI() {
  const toggleBtn = document.getElementById('modal-edit-toggle');
  const saveButton = document.getElementById('modal-save-button');
  if (toggleBtn) {
    toggleBtn.style.display = modalMode === 'edit-plan' ? '' : 'none';
    toggleBtn.textContent = modalMode === 'edit-plan' ? 'Exit' : 'Edit Mode';
    toggleBtn.className = 'btn btn-secondary';
  }
  if (saveButton) {
    if (modalMode === 'add-worker') {
      saveButton.style.display = '';
    } else if (modalMode === 'edit-plan') {
      saveButton.style.display = '';
    } else {
      saveButton.style.display = 'none';
    }
  }
}

function toggleModalEditMode() {
  if (modalMode !== 'edit-plan') return;
  closeModal();
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
  const times = getShiftTimes(defaultTask, targetDay);

  // Initialize skills per modality from task's skill_overrides
  const skillsByModality = {};
  MODALITIES.forEach(mod => {
    const modKey = mod.toLowerCase();
    skillsByModality[modKey] = {};
    SKILLS.forEach(skill => {
      // Check for skill_modality format (e.g., "notfall_ct") first, then skill-only
      const skillModKey = `${skill}_${modKey}`;
      const overrides = defaultTask.skill_overrides || {};
      if (overrides[skillModKey] !== undefined) {
        skillsByModality[modKey][skill] = overrides[skillModKey];
      } else if (overrides[skill] !== undefined) {
        skillsByModality[modKey][skill] = overrides[skill];
      } else {
        skillsByModality[modKey][skill] = 0;  // Default to passive
      }
    });
  });

  addWorkerModalState.tasks.push({
    task: defaultTask.name || '',
    start_time: times.start,
    end_time: times.end,
    modifier: defaultTask.modifier || 1.0,
    counts_for_hours: defaultTask.counts_for_hours !== false,
    skillsByModality: skillsByModality
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

function updateAddWorkerTask(idx, field, value) {
  if (!addWorkerModalState.tasks[idx]) return;
  addWorkerModalState.tasks[idx][field] = value;

  // If task changed, update times, modifier, and skills per modality (preload from config)
  if (field === 'task') {
    const taskConfig = TASK_ROLES.find(t => t.name === value);
    if (taskConfig) {
      const task = addWorkerModalState.tasks[idx];
      const isGap = taskConfig.type === 'gap';
      const overrides = taskConfig.skill_overrides || {};

      // Update counts_for_hours from task config
      task.counts_for_hours = taskConfig.counts_for_hours !== false;

      if (isGap) {
        // Gap selected - set all skills to -1 and use times for target day
        task.modifier = 1.0;
        task.counts_for_hours = false;  // Gaps typically don't count for hours

        // Get times for the target day (based on modal's tab)
        const targetDay = getTargetWeekdayName(addWorkerModalState.tab || currentTab);
        const parsedTimes = getGapTimeRange(taskConfig, targetDay) || ['12:00', '13:00'];
        [task.start_time, task.end_time] = parsedTimes;

        // Set ALL skills to -1 for gaps across all modalities
        MODALITIES.forEach(mod => {
          const modKey = mod.toLowerCase();
          if (!task.skillsByModality[modKey]) task.skillsByModality[modKey] = {};
          SKILLS.forEach(skill => {
            task.skillsByModality[modKey][skill] = -1;
          });
        });
      } else {
        // Regular shift selected - preload skills from task's skill_overrides (like CSV loading)
        const targetDay = getTargetWeekdayName(addWorkerModalState.tab || currentTab);
        const times = getShiftTimes(taskConfig, targetDay);
        task.start_time = times.start;
        task.end_time = times.end;
        task.modifier = taskConfig.modifier || 1.0;

        // Apply skill_overrides per modality (supports "Skill_modality" format like CSV loading)
        MODALITIES.forEach(mod => {
          const modKey = mod.toLowerCase();
          if (!task.skillsByModality[modKey]) task.skillsByModality[modKey] = {};
          SKILLS.forEach(skill => {
            // Check for skill_modality format (e.g., "notfall_ct") first
            const skillModKey = `${skill}_${modKey}`;
            if (overrides[skillModKey] !== undefined) {
              task.skillsByModality[modKey][skill] = overrides[skillModKey];
            } else if (overrides[skill] !== undefined) {
              // Skill-only override applies to all modalities
              task.skillsByModality[modKey][skill] = overrides[skill];
            } else if (overrides['all'] !== undefined) {
              // "all" shortcut
              task.skillsByModality[modKey][skill] = overrides['all'];
            } else {
              task.skillsByModality[modKey][skill] = 0;  // Default to passive
            }
          });
        });

        // Apply worker roster exclusions (-1) - roster -1 always wins
        const workerInput = document.getElementById('add-worker-name-input');
        const inputValue = workerInput ? workerInput.value.trim() : '';
        const { id: workerId } = parseWorkerInput(inputValue);
        if (workerId && WORKER_SKILLS[workerId]) {
          applyRosterToSkillsByModality(task.skillsByModality, workerId);
        }
      }

      renderAddWorkerModalContent();
    }
  }
}

function updateAddWorkerSkill(idx, modality, skill, value) {
  if (!addWorkerModalState.tasks[idx]) return;
  const task = addWorkerModalState.tasks[idx];
  if (!task.skillsByModality[modality]) task.skillsByModality[modality] = {};
  const raw = (value || '').toString().trim();
  task.skillsByModality[modality][skill] = raw === 'w' ? 'w' : (parseInt(raw, 10) || 0);
}

// Helper: apply roster exclusions to skillsByModality (roster -1 always wins)
// Roster structure is modality-scoped: { modality: { skill: value } }
function applyRosterToSkillsByModality(skillsByModality, workerName) {
  if (!workerName || !WORKER_SKILLS[workerName]) return;
  const workerRoster = WORKER_SKILLS[workerName];
  MODALITIES.forEach(mod => {
    const modKey = mod.toLowerCase();
    if (!skillsByModality[modKey]) skillsByModality[modKey] = {};
    // Get roster skills for this specific modality
    const modalityRoster = workerRoster[modKey] || {};
    SKILLS.forEach(skill => {
      // Roster -1 always wins (cannot be overridden)
      if (modalityRoster[skill] === -1) {
        skillsByModality[modKey][skill] = -1;
      }
    });
  });
}

function onAddWorkerNameChange() {
  const workerInput = document.getElementById('add-worker-name-input');
  const inputValue = workerInput ? workerInput.value.trim() : '';

  // Parse "Full Name (ID)" format to extract the worker ID
  const { id: workerId } = parseWorkerInput(inputValue);

  if (workerId && WORKER_SKILLS[workerId]) {
    // Apply roster -1 values to all modalities in all tasks
    addWorkerModalState.tasks.forEach(task => {
      if (task.skillsByModality) {
        applyRosterToSkillsByModality(task.skillsByModality, workerId);
      }
    });
    renderAddWorkerModalContent();
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
      const modalities = {};
      const skillsByModality = task.skillsByModality || {};

      Object.entries(skillsByModality).forEach(([modKey, modSkills]) => {
        modalities[modKey] = {
          skills: { ...(modSkills || {}) }
        };
      });

      return {
        start_time: task.start_time,
        end_time: task.end_time,
        modifier: task.modifier,
        counts_for_hours: isGap ? task.counts_for_hours === true : task.counts_for_hours !== false,
        task: task.task,
        row_type: isGap ? 'gap' : 'shift',
        modalities
      };
    });

    const response = await fetch(workerEndpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        worker: workerLabel,
        shifts
      })
    });

    if (!response.ok) {
      const errData = await response.json().catch(() => ({}));
      throw new Error(errData.error || 'Failed to add worker plan');
    }

    closeModal();
    showMessage('success', `${getWorkerDisplayName(workerId)} added/updated`);
    await loadData();
  } catch (error) {
    showMessage('error', error.message);
  }
}

function getGapCountsForHours(taskName) {
  const taskConfig = TASK_ROLES.find(t => t.name === taskName);
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
    const msg = `Add ${duration}-min break for ${group.worker}?\n\nTime: ${gapStart} - ${gapEnd}`;
    if (!confirm(msg)) return;
  }

  try {
    // Create standalone gap intent rows via add-gap API per modality row_index.
    const addEndpoint = tab === 'today' ? '/api/live-schedule/add-gap' : '/api/prep-next-day/add-gap';
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

    const gapPayloads = Array.from(rowIndexByModality.entries()).map(([modality, rowIndex]) => (
      fetch(addEndpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          modality,
          row_index: rowIndex,
          gap_type: gapType,
          gap_start: gapStart,
          gap_end: gapEnd,
          gap_counts_for_hours: getGapCountsForHours(gapType)
        })
      })
    ));

    const responses = await Promise.all(gapPayloads);
    const failedResponse = responses.find(response => !response.ok);
    if (failedResponse) {
      const errData = await failedResponse.json().catch(() => ({}));
      throw new Error(errData.error || 'Failed to create gap');
    }

    showMessage('success', `Added break (${gapStart}-${gapEnd}) for ${group.worker}`);
    await loadData();
  } catch (error) {
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
async function loadFromCSV(mode) {
  if (mode === 'today') {
    const hasPendingChanges = Object.keys(pendingChanges.today || {}).length > 0;
    const message = hasPendingChanges
      ? 'HARD RELOAD TODAY will discard unsaved Quick Edit changes and reset today from the Master CSV. Continue?'
      : 'HARD RELOAD TODAY will reset today from the Master CSV. Continue?';
    if (!window.confirm(message)) {
      return;
    }
  }

  const statusId = mode === 'today' ? 'load-status-today' : 'load-status-tomorrow';
  const loadStatus = document.getElementById(statusId);
  loadStatus.textContent = 'Loading...';

  const endpoint = mode === 'today' ? '/load-today-from-master' : '/preload-from-master';
  const targetDate = mode === 'today' ? null : (document.getElementById('prep-target-date')?.value || prepTargetDate);
  const payload = targetDate ? { target_date: targetDate } : null;

  try {
    const response = await fetch(endpoint, {
      method: 'POST',
      headers: payload ? { 'Content-Type': 'application/json' } : undefined,
      body: payload ? JSON.stringify(payload) : undefined,
    });
    const result = await response.json();

    if (response.ok) {
      loadStatus.textContent = result.message || 'Loaded!';
      loadStatus.style.color = '#28a745';
      if (mode === 'next' && result.target_date) {
        setPrepTargetMeta({ dateValue: result.target_date });
        updatePrepTargetUI();
      }
      await loadData();
    } else {
      loadStatus.textContent = result.error || 'Error';
      loadStatus.style.color = '#dc3545';
    }
  } catch (error) {
    loadStatus.textContent = 'Error: ' + error.message;
    loadStatus.style.color = '#dc3545';
  }

  setTimeout(() => { loadStatus.textContent = ''; }, 5000);
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
