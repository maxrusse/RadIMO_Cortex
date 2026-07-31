// State
const INITIAL_TAB = (typeof CONFIG !== 'undefined' && CONFIG.initial_tab) ? CONFIG.initial_tab : 'today';
let currentTab = INITIAL_TAB;
let rawData = { today: {}, tomorrow: {} };  // Raw modality data
let entriesData = { today: [], tomorrow: [] };  // Grouped by worker -> shifts (time-based)
let workerCounts = { today: {}, tomorrow: {} };  // Count entries per worker for duplicate detection
let currentEditEntry = null;
let editPlanDraft = null;
let dataLoaded = { today: false, tomorrow: false };  // Track which tabs have been loaded
let editMode = { today: false, tomorrow: false };  // Inline edit mode defaults to OFF - user decides which edit mode to use
let pendingChanges = { today: {}, tomorrow: {} };  // Track unsaved inline changes
let snapshotVersions = { today: null, tomorrow: null };  // Optimistic-lock token per tab
let workerRevisions = { today: {}, tomorrow: {} };  // Worker-scoped optimistic-lock token for modal editing
let tableFilters = { today: { modality: '', skill: '', hideZero: true }, tomorrow: { modality: '', skill: '', hideZero: true } };
let displayOrder = 'modality-first';  // 'modality-first' or 'skill-first'
let sortState = { today: { column: 'shift', direction: 'asc' }, tomorrow: { column: 'shift', direction: 'asc' } };
let modalMode = 'edit';
let lastAddedShiftMeta = null;
let loadRequestId = { today: 0, tomorrow: 0 };
let prepAutoRefreshInterval = { today: null, tomorrow: null };
const GERMAN_WEEKDAYS = ['Sonntag', 'Montag', 'Dienstag', 'Mittwoch', 'Donnerstag', 'Freitag', 'Samstag'];
let prepTargetDate = CONFIG.prep_target_date || null;
let prepTargetWeekday = CONFIG.prep_target_weekday_name || null;
let prepTargetDateGerman = CONFIG.prep_target_date_german || null;
const prepMinDate = CONFIG.prep_min_date || null;

// Add Worker Modal state
let addWorkerModalState = {
  tab: null,
  tasks: [],  // Array of { task, modality, start_time, end_time, modifier, skills }
  containerId: 'modal-content'
};

function buildWorkerSortKey(name) {
  return window.WorkerNameUtils.buildSortKey(name);
}


/**
 * Parse worker input like "Dr. Name (ID)" or just "ID".
 * Returns { id, fullName } where id is the canonical worker ID.
 */
function findKnownWorkerIdByLabel(inputValue) {
  const normalizedInput = String(inputValue || '').trim().toLowerCase();
  if (!normalizedInput) return null;

  const workerIds = new Set([
    ...Object.keys(WORKER_NAMES || {}),
    ...Object.keys(WORKER_SKILLS || {}),
  ]);

  for (const workerId of workerIds) {
    const candidates = new Set([
      String(workerId || '').trim(),
      String(getWorkerDisplayName(workerId) || '').trim(),
      String(WORKER_NAMES?.[workerId] || '').trim(),
      String(WORKER_SKILLS?.[workerId]?.full_name || '').trim(),
    ]);
    for (const candidate of candidates) {
      if (candidate && candidate.toLowerCase() === normalizedInput) {
        return workerId;
      }
    }
  }

  return null;
}

function parseWorkerInput(inputValue) {
  const trimmed = (inputValue || '').trim();
  // Match pattern: "anything (ID)" where ID is inside parentheses
  const match = trimmed.match(/^(.+?)\s*\(([^)]+)\)$/);
  if (match) {
    return { id: match[2].trim(), fullName: trimmed, matchedExisting: true };
  }
  const knownWorkerId = findKnownWorkerIdByLabel(trimmed);
  if (knownWorkerId) {
    return { id: knownWorkerId, fullName: null, matchedExisting: true };
  }
  // No parentheses - treat as plain ID
  return { id: trimmed, fullName: null, matchedExisting: false };
}

/**
 * Get display name for a worker ID.
 * Returns "Full Name (ID)" format if name is known, otherwise just the ID.
 */
function getWorkerDisplayName(workerId) {
  return window.WorkerNameUtils.formatDisplayName(WORKER_NAMES[workerId] || workerId, workerId);
}

/**
 * Get shift times from task config.
 * Structure: task.times = { default: "07:00-15:00", Freitag: "07:00-13:00", ... }
 * @param {Object} taskConfig - The task role configuration
 * @param {string} targetDay - German weekday name (Montag, Dienstag, etc.)
 * @returns {Object} { start: "07:00", end: "15:00" }
 */
function getShiftTimes(taskConfig, targetDay) {
  const defaultTimes = { start: '07:00', end: '15:00' };

  if (!taskConfig) return defaultTimes;

  const timeStr = resolveDayTimes(taskConfig.times, targetDay) || '07:00-15:00';
  if (typeof timeStr !== 'string') {
    return defaultTimes;
  }
  const [start, end] = timeStr.split('-');
  return { start: start?.trim() || '07:00', end: end?.trim() || '15:00' };
}

function resolveDayTimes(timesConfig, targetDay) {
  const times = timesConfig || {};
  if (Object.keys(times).length === 0) return null;
  if (targetDay && times[targetDay]) return times[targetDay];
  return times.default || null;
}

function resolveDayModifier(modifierConfig, targetDay, defaultValue = 1.0) {
  if (modifierConfig === null || modifierConfig === undefined || modifierConfig === '') {
    return defaultValue;
  }
  if (typeof modifierConfig !== 'object' || Array.isArray(modifierConfig)) {
    const parsed = parseFloat(modifierConfig);
    return Number.isNaN(parsed) ? defaultValue : parsed;
  }
  const rawValue = (
    (targetDay && modifierConfig[targetDay] !== undefined) ? modifierConfig[targetDay] :
    modifierConfig.default
  );
  const parsed = parseFloat(rawValue);
  return Number.isNaN(parsed) ? defaultValue : parsed;
}

// Active skill values for filtering - excludes 0 and -1 (only shows explicitly active workers)
const ACTIVE_SKILL_VALUES = new Set([1, '1', 'w', 'W']);

// Weighted skill markers (normalized to 'w' internally)
const WEIGHTED_MARKERS = new Set(['w', 'W', 2, '2']);

function normalizeSkillValueJS(value) {
  if (value === undefined || value === null) return 0;
  if (WEIGHTED_MARKERS.has(value)) return 'w';
  if (typeof value === 'string' && value.trim() === '') return 0;
  const parsed = parseInt(value, 10);
  return isNaN(parsed) ? value : parsed;
}

function isWeightedSkill(value) {
  return WEIGHTED_MARKERS.has(value);
}

function getModalShifts(group) {
  if (!group) return [];
  if (currentEditEntry && editPlanDraft && editPlanDraft.worker === group.worker) {
    return editPlanDraft.shifts || [];
  }
  return group.modalShiftsArray || group.shiftsArray || [];
}

function getTableShifts(group) {
  if (!group) return [];
  return group.tableShiftsArray || group.modalShiftsArray || group.shiftsArray || [];
}

function setEditPlanDraftFromGroup(group, options = {}) {
  if (!group) return;
  const shouldReset = options.force || !editPlanDraft || editPlanDraft.worker !== group.worker;
  if (!shouldReset) return;
  const sourceShifts = getTableShifts(group);
  editPlanDraft = {
    worker: group.worker,
    shifts: JSON.parse(JSON.stringify(sourceShifts))
  };
  ensureEditPlanDraftBaseSkills();
}

function clearEditPlanDraft() {
  editPlanDraft = null;
}

function getWorkerRevision(tab, workerName) {
  return workerRevisions[tab]?.[workerName] || null;
}

function cloneSkillMap(skillMap) {
  return JSON.parse(JSON.stringify(skillMap || {}));
}

function applyTrainingToSkillValue(value, trainingEnabled) {
  const normalized = normalizeSkillValueJS(value);
  if (normalized === -1) return -1;
  if (!trainingEnabled && isWeightedSkill(normalized)) return -1;
  return normalized;
}

function applyTrainingToSkillMap(skillMap, trainingEnabled) {
  const transformed = {};
  Object.entries(skillMap || {}).forEach(([skill, value]) => {
    transformed[skill] = applyTrainingToSkillValue(value, trainingEnabled);
  });
  return transformed;
}

function ensureEditPlanDraftBaseSkills() {
  if (!editPlanDraft || !Array.isArray(editPlanDraft.shifts)) return;
  editPlanDraft.shifts.forEach(shift => {
    Object.entries(shift.modalities || {}).forEach(([modKey, modData]) => {
      if (!modData) return;
      if (!modData.baseSkills) {
        modData.baseSkills = cloneSkillMap(modData.skills || {});
      }
      if (!modData.skills) {
        modData.skills = cloneSkillMap(modData.baseSkills);
      }
    });
  });
}

function updateEditPlanDraftShift(shiftIdx, updates) {
  if (!editPlanDraft || !editPlanDraft.shifts) return;
  const shift = editPlanDraft.shifts[shiftIdx];
  if (!shift) return;
  if (updates.start_time !== undefined) shift.start_time = updates.start_time;
  if (updates.end_time !== undefined) shift.end_time = updates.end_time;
  if (updates.Modifier !== undefined) shift.modifier = updates.Modifier;
  if (updates.counts_for_hours !== undefined) shift.counts_for_hours = updates.counts_for_hours;
  if (updates.tasks !== undefined) shift.task = updates.tasks;
  if (updates.training !== undefined) shift.training = Boolean(updates.training);
  if (updates.row_type !== undefined) {
    shift.row_type = updates.row_type;
    shift.is_gap_entry = String(updates.row_type).toLowerCase().includes('gap');
  }
  if (updates.start_time !== undefined || updates.end_time !== undefined) {
    const start = updates.start_time !== undefined ? updates.start_time : shift.start_time;
    const end = updates.end_time !== undefined ? updates.end_time : shift.end_time;
    shift.timeSegments = [{ start, end }];
  }
}

function updateEditPlanDraftShiftSkills(shiftIdx, skillUpdatesByMod) {
  if (!editPlanDraft || !editPlanDraft.shifts) return;
  const shift = editPlanDraft.shifts[shiftIdx];
  if (!shift || !shift.modalities) return;
  Object.entries(skillUpdatesByMod || {}).forEach(([modKey, skillUpdates]) => {
    if (!shift.modalities[modKey]) return;
    if (!shift.modalities[modKey].skills) shift.modalities[modKey].skills = {};
    Object.entries(skillUpdates || {}).forEach(([skill, value]) => {
      shift.modalities[modKey].skills[skill] = value;
    });
  });
}

function ensureEditPlanDraftModality(shiftIdx, modKey) {
  if (!editPlanDraft || !editPlanDraft.shifts) return null;
  const shift = editPlanDraft.shifts[shiftIdx];
  if (!shift) return null;
  if (!shift.modalities) shift.modalities = {};
  if (!shift.modalities[modKey]) {
    const skills = {};
    SKILLS.forEach(skill => {
      skills[skill] = -1;
    });
    shift.modalities[modKey] = {
      row_index: -1,
      row_uid: null,
      edit_key: null,
      modifier: shift.modifier || 1.0,
      baseSkills: cloneSkillMap(skills),
      skills,
      materialize: false
    };
  }
  return shift.modalities[modKey];
}

function isSyntheticEmptyEditPlanModality(modData) {
  if (!modData) return false;
  const rowIndex = Number.isInteger(modData.row_index) ? modData.row_index : -1;
  if (rowIndex >= 0 || modData.materialize === true) return false;
  const skillMap = modData.baseSkills || modData.skills || {};
  return SKILLS.every(skill => normalizeSkillValueJS(skillMap?.[skill]) === -1);
}

function pruneSyntheticEmptyEditPlanModalities(shiftIdx) {
  if (!editPlanDraft || !editPlanDraft.shifts) return;
  const shift = editPlanDraft.shifts[shiftIdx];
  if (!shift || !shift.modalities) return;
  Object.entries(shift.modalities).forEach(([modKey, modData]) => {
    if (isSyntheticEmptyEditPlanModality(modData)) {
      delete shift.modalities[modKey];
    }
  });
}

function pruneSyntheticEmptyEditPlanDraft() {
  if (!editPlanDraft || !Array.isArray(editPlanDraft.shifts)) return;
  editPlanDraft.shifts.forEach((_shift, shiftIdx) => {
    pruneSyntheticEmptyEditPlanModalities(shiftIdx);
  });
}

function updateEditPlanDraftShiftSkill(shiftIdx, modKey, skill, value, trainingEnabled = null) {
  if (!editPlanDraft || !editPlanDraft.shifts) return null;
  const shift = editPlanDraft.shifts[shiftIdx];
  if (!shift) return null;
  const ensuredModData = ensureEditPlanDraftModality(shiftIdx, modKey);
  if (!ensuredModData) return null;
  const modData = shift.modalities[modKey];
  if (!modData.baseSkills) {
    modData.baseSkills = cloneSkillMap(modData.skills || {});
  }
  modData.baseSkills[skill] = value;
  const training = trainingEnabled === null ? shift.training !== false : Boolean(trainingEnabled);
  const effectiveValue = applyTrainingToSkillValue(value, training);
  modData.skills[skill] = effectiveValue;
  return effectiveValue;
}

function applyEditPlanDraftShiftTraining(shiftIdx, trainingEnabled) {
  if (!editPlanDraft || !editPlanDraft.shifts) return null;
  const shift = editPlanDraft.shifts[shiftIdx];
  if (!shift || !shift.modalities) return null;
  shift.training = Boolean(trainingEnabled);
  Object.entries(shift.modalities).forEach(([modKey, modData]) => {
    if (!modData) return;
    if (!modData.baseSkills) {
      modData.baseSkills = cloneSkillMap(modData.skills || {});
    }
    modData.skills = applyTrainingToSkillMap(modData.baseSkills, shift.training);
  });
  return shift;
}

function displaySkillValue(value) {
  return isWeightedSkill(value) ? 'w' : value;
}

function isActiveSkillValue(value) {
  return ACTIVE_SKILL_VALUES.has(value);
}

// Check if skill value is non-negative (0, 1, or weighted)
function isNonNegativeSkillValue(value) {
  const v = normalizeSkillValueJS(value);
  return v === 0 || v === 1 || isWeightedSkill(v);
}

// Helper: Get regular shifts (type='shift' and counts_for_hours !== false)
function getShiftRoles() {
  return TASK_ROLES.filter(t => t.type === 'shift' && t.counts_for_hours !== false);
}

// Helper: Get blocker shifts (type='shift' and counts_for_hours === false)
function getBlockerShiftRoles() {
  return TASK_ROLES.filter(t => t.type === 'shift' && t.counts_for_hours === false);
}

// Helper: Get gaps (type='gap')
function getGapTasks() {
  return TASK_ROLES.filter(t => t.type === 'gap');
}

function sortTasksByName(tasks) {
  return [...tasks].sort((a, b) => {
    const aName = String(a?.name || '').trim();
    const bName = String(b?.name || '').trim();
    return aName.localeCompare(bName, undefined, { numeric: true, sensitivity: 'base' });
  });
}

// Helper: Get the target weekday name (German) based on current tab
// For "today" tab: use current day
// For "tomorrow" tab: use next workday (skip weekends)
function getTargetWeekdayName(tab) {
  const now = new Date();
  if (tab === 'today') {
    return GERMAN_WEEKDAYS[now.getDay()];
  }
  if (prepTargetWeekday) {
    return prepTargetWeekday;
  }
  if (prepTargetDate) {
    const targetDate = new Date(`${prepTargetDate}T00:00:00`);
    if (!Number.isNaN(targetDate.getTime())) {
      return GERMAN_WEEKDAYS[targetDate.getDay()];
    }
  }
  const fallbackDate = new Date(now);
  fallbackDate.setDate(fallbackDate.getDate() + 1);
  return GERMAN_WEEKDAYS[fallbackDate.getDay()];
}

function setPrepTargetMeta({ dateValue, weekdayName, dateGerman }) {
  if (dateValue) {
    prepTargetDate = dateValue;
  }
  if (weekdayName) {
    prepTargetWeekday = weekdayName;
  } else if (prepTargetDate) {
    const targetDate = new Date(`${prepTargetDate}T00:00:00`);
    if (!Number.isNaN(targetDate.getTime())) {
      prepTargetWeekday = GERMAN_WEEKDAYS[targetDate.getDay()];
    }
  }
  if (dateGerman) {
    prepTargetDateGerman = dateGerman;
  } else if (prepTargetDate) {
    const targetDate = new Date(`${prepTargetDate}T00:00:00`);
    if (!Number.isNaN(targetDate.getTime())) {
      prepTargetDateGerman = targetDate.toLocaleDateString('de-DE');
    }
  }
}

// Helper: Check if a task name is a gap (using config, not string matching)
function isGapTask(taskName) {
  if (!taskName) return false;
  const taskConfig = resolveTaskConfigByName(taskName);
  return taskConfig?.type === 'gap';
}

// Cache for pre-built dropdown options (performance optimization)
// Key format: targetDay -> { baseHtmlNoGaps, baseHtmlWithGaps, optionsByValue, firstShiftName }
let taskOptionsCacheByDay = new Map();

function normalizeTaskTimeRanges(dayTimes) {
  if (typeof dayTimes === 'string') {
    return dayTimes.trim() ? [dayTimes.trim()] : [];
  }
  if (Array.isArray(dayTimes)) {
    return dayTimes
      .map(entry => (typeof entry === 'string' ? entry.trim() : ''))
      .filter(Boolean);
  }
  return [];
}

function buildGapOptionValue(baseName, persistedName, timeRange) {
  return `__gap__|${baseName}|${persistedName}|${timeRange}`;
}

function parseGapOptionValue(value) {
  if (typeof value !== 'string' || !value.startsWith('__gap__|')) {
    return null;
  }
  const parts = value.split('|');
  if (parts.length !== 4) return null;
  const [, baseName, persistedName, timeRange] = parts;
  const parsed = parseDayTimes(timeRange);
  if (!parsed) return null;
  const [start, end] = parsed;
  return { baseName, persistedName, timeRange, start, end };
}

function resolveGapBlocksForTask(taskConfig, targetDay) {
  if (!taskConfig || taskConfig.type !== 'gap') return [];
  const blocks = [];

  const addBlocks = (persistedName, timesConfig) => {
    const dayTimes = typeof resolveDayTimes === 'function'
      ? resolveDayTimes(timesConfig || {}, targetDay)
      : ((timesConfig || {})[targetDay] || (timesConfig || {}).default);
    normalizeTaskTimeRanges(dayTimes).forEach(timeRange => {
      const parsed = parseDayTimes(timeRange);
      if (!parsed) return;
      const [start, end] = parsed;
      blocks.push({
        baseName: taskConfig.name,
        persistedName: persistedName || taskConfig.name,
        timeRange,
        start,
        end
      });
    });
  };

  const segments = Array.isArray(taskConfig.segments) ? taskConfig.segments : [];
  if (segments.length > 0) {
    segments.forEach(segment => {
      addBlocks(segment?.label || taskConfig.name, segment?.times || {});
    });
    return blocks;
  }

  addBlocks(taskConfig.name, taskConfig.times || {});
  return blocks;
}

function buildGapTaskOptionConfig(taskConfig, targetDay, gapBlock) {
  const optionValue = buildGapOptionValue(taskConfig.name, gapBlock.persistedName, gapBlock.timeRange);
  return {
    ...taskConfig,
    name: optionValue,
    persisted_name: gapBlock.persistedName,
    display_name: `${gapBlock.persistedName} (${gapBlock.start}-${gapBlock.end})`,
    times: { [targetDay || 'default']: gapBlock.timeRange },
    segments: []
  };
}

function resolveTaskConfigByName(taskName, targetDay = null) {
  if (!taskName) return null;
  const directMatch = TASK_ROLES.find(t => t.name === taskName);
  if (directMatch) return directMatch;

  const effectiveTargetDay = targetDay || getTargetWeekdayName(currentTab);
  const parsedGapValue = parseGapOptionValue(taskName);
  if (parsedGapValue) {
    const baseGapTask = getGapTasks().find(t => t.name === parsedGapValue.baseName);
    if (!baseGapTask) return null;
    return buildGapTaskOptionConfig(baseGapTask, effectiveTargetDay, parsedGapValue);
  }

  const matchingGapConfigs = [];
  getGapTasks().forEach(taskConfig => {
    resolveGapBlocksForTask(taskConfig, effectiveTargetDay).forEach(gapBlock => {
      if (gapBlock.persistedName === taskName) {
        matchingGapConfigs.push(buildGapTaskOptionConfig(taskConfig, effectiveTargetDay, gapBlock));
      }
    });
  });
  if (matchingGapConfigs.length === 1) {
    return matchingGapConfigs[0];
  }

  return null;
}

function isGapAvailableForDay(taskConfig, targetDay) {
  if (!taskConfig || taskConfig.type !== 'gap') return true;
  return resolveGapBlocksForTask(taskConfig, targetDay).length > 0;
}

// Build and cache dropdown options (called once, reused many times)
function buildTaskOptionsCache(targetDay) {
  const cacheKey = targetDay || 'default';
  if (taskOptionsCacheByDay.has(cacheKey)) {
    return taskOptionsCacheByDay.get(cacheKey);
  }

  const shifts = sortTasksByName(getShiftRoles());
  const blockerShifts = sortTasksByName(getBlockerShiftRoles());
  const gaps = sortTasksByName(getGapTasks().filter(t => isGapAvailableForDay(t, targetDay)));

  // Build base HTML without selection (for includeGaps: false)
  let baseHtmlNoGaps = '<option value="">-- Select --</option>';
  // Build base HTML with gaps (for includeGaps: true)
  let baseHtmlWithGaps = '<option value="">-- Select --</option>';

  // Map of option value -> { html, htmlSelected } for quick selection updates
  const optionsByValue = new Map();
  const optionDescriptors = [];

  // Regular shifts group
  if (shifts.length > 0) {
    const optgroupStart = '<optgroup label="Shifts">';
    const optgroupEnd = '</optgroup>';
    baseHtmlNoGaps += optgroupStart;
    baseHtmlWithGaps += optgroupStart;

    shifts.forEach(t => {
      const escapedName = escapeHtml(t.name);
      const modifier = resolveDayModifier(t.modifier, targetDay);
      const dataAttrs = `data-type="shift" data-modalities='${JSON.stringify(t.modalities || [])}' data-shift="${escapeHtml(t.shift || 'Fruehdienst')}" data-skills='${JSON.stringify(t.skill_overrides || {})}' data-modifier="${modifier}"`;
      const optionHtml = `<option value="${escapedName}" ${dataAttrs}>${escapedName}</option>`;
      const optionHtmlSelected = `<option value="${escapedName}" ${dataAttrs} selected>${escapedName}</option>`;

      baseHtmlNoGaps += optionHtml;
      baseHtmlWithGaps += optionHtml;
      optionsByValue.set(t.name, { html: optionHtml, htmlSelected: optionHtmlSelected, isShift: true });
    });

    baseHtmlNoGaps += optgroupEnd;
    baseHtmlWithGaps += optgroupEnd;
  }

  // Blocker shifts group
  if (blockerShifts.length > 0) {
    const optgroupStart = '<optgroup label="Blocker Shifts">';
    const optgroupEnd = '</optgroup>';
    baseHtmlNoGaps += optgroupStart;
    baseHtmlWithGaps += optgroupStart;

    blockerShifts.forEach(t => {
      const escapedName = escapeHtml(t.name);
      const modifier = resolveDayModifier(t.modifier, targetDay);
      const dataAttrs = `data-type="shift" data-modalities='${JSON.stringify(t.modalities || [])}' data-shift="${escapeHtml(t.shift || 'Fruehdienst')}" data-skills='${JSON.stringify(t.skill_overrides || {})}' data-modifier="${modifier}" data-counts-for-hours="false"`;
      const optionHtml = `<option value="${escapedName}" ${dataAttrs}>${escapedName}</option>`;
      const optionHtmlSelected = `<option value="${escapedName}" ${dataAttrs} selected>${escapedName}</option>`;

      baseHtmlNoGaps += optionHtml;
      baseHtmlWithGaps += optionHtml;
      optionsByValue.set(t.name, { html: optionHtml, htmlSelected: optionHtmlSelected, isShift: true });
    });

    baseHtmlNoGaps += optgroupEnd;
    baseHtmlWithGaps += optgroupEnd;
  }

  // Gaps group (only for baseHtmlWithGaps)
  if (gaps.length > 0) {
    baseHtmlWithGaps += '<optgroup label="Gaps">';
    gaps.forEach(t => {
      const gapBlocks = resolveGapBlocksForTask(t, targetDay);
      gapBlocks.forEach(gapBlock => {
        const optionTask = buildGapTaskOptionConfig(t, targetDay, gapBlock);
        const escapedValue = escapeHtml(optionTask.name);
        const escapedLabel = escapeHtml(optionTask.display_name || optionTask.persisted_name || optionTask.name);
        const dataAttrs = `data-type="gap" data-times='${JSON.stringify(optionTask.times || {})}' data-persisted-name="${escapeHtml(optionTask.persisted_name || t.name)}"`;
        const optionHtml = `<option value="${escapedValue}" ${dataAttrs}>${escapedLabel}</option>`;
        const optionHtmlSelected = `<option value="${escapedValue}" ${dataAttrs} selected>${escapedLabel}</option>`;

        baseHtmlWithGaps += optionHtml;
        optionsByValue.set(optionTask.name, { html: optionHtml, htmlSelected: optionHtmlSelected, isShift: false });
        optionDescriptors.push({
          value: optionTask.name,
          persistedName: optionTask.persisted_name || t.name,
          start: gapBlock.start,
          end: gapBlock.end
        });
      });
    });
    baseHtmlWithGaps += '</optgroup>';
  }

  // Get first shift name for autoSelectFirst feature
  const firstShiftName = shifts.length > 0 ? shifts[0].name : (blockerShifts.length > 0 ? blockerShifts[0].name : null);

  const taskOptionsCache = {
    baseHtmlNoGaps,
    baseHtmlWithGaps,
    optionsByValue,
    optionDescriptors,
    firstShiftName
  };

  taskOptionsCacheByDay.set(cacheKey, taskOptionsCache);
  return taskOptionsCache;
}

// Clear cache when task roles change (called externally if config updates)
function clearTaskOptionsCache() {
  taskOptionsCacheByDay = new Map();
}

// Helper: Render task/role dropdown with optgroups for Shifts vs Gaps
// autoSelectFirst: if true and no selectedValue, auto-select the first shift option
// OPTIMIZED: Uses cached base HTML and only modifies selection
function renderTaskOptionsWithGroups(selectedValue = '', includeGaps = false, autoSelectFirst = false, targetDay = null, selectedRange = null) {
  const effectiveTargetDay = targetDay || getTargetWeekdayName(currentTab);
  const cache = buildTaskOptionsCache(effectiveTargetDay);

  // Determine effective selected value
  let effectiveSelected = selectedValue;
  if (autoSelectFirst && !selectedValue && cache.firstShiftName) {
    effectiveSelected = cache.firstShiftName;
  }

  // If no selection needed, return cached base HTML directly
  if (!effectiveSelected) {
    return includeGaps ? cache.baseHtmlWithGaps : cache.baseHtmlNoGaps;
  }

  // Need to mark one option as selected - use string replacement for speed
  const baseHtml = includeGaps ? cache.baseHtmlWithGaps : cache.baseHtmlNoGaps;
  const optionData = cache.optionsByValue.get(effectiveSelected);

  if (optionData) {
    // Replace the unselected option with selected version
    return baseHtml.replace(optionData.html, optionData.htmlSelected);
  }

  if (selectedValue && includeGaps) {
    const matchingDescriptors = cache.optionDescriptors.filter(desc => desc.persistedName === selectedValue);
    if (selectedRange?.start && selectedRange?.end) {
      const exactTimed = matchingDescriptors.find(desc => desc.start === selectedRange.start && desc.end === selectedRange.end);
      if (exactTimed) {
        const timedOption = cache.optionsByValue.get(exactTimed.value);
        if (timedOption) return baseHtml.replace(timedOption.html, timedOption.htmlSelected);
      }
    }
    if (matchingDescriptors.length === 1) {
      const uniqueOption = cache.optionsByValue.get(matchingDescriptors[0].value);
      if (uniqueOption) return baseHtml.replace(uniqueOption.html, uniqueOption.htmlSelected);
    }
  }

  // Selected value not found in cache, add a fallback option to preserve existing value
  if (!selectedValue) {
    return baseHtml;
  }
  const taskConfig = resolveTaskConfigByName(selectedValue, effectiveTargetDay);
  if (!taskConfig) {
    return baseHtml;
  }
  const escapedName = escapeHtml(taskConfig.name);
  const escapedLabel = escapeHtml(taskConfig.display_name || taskConfig.persisted_name || taskConfig.name);
  let dataAttrs = '';
  if (taskConfig.type === 'gap') {
    dataAttrs = `data-type="gap" data-times='${JSON.stringify(taskConfig.times || {})}' data-persisted-name="${escapeHtml(taskConfig.persisted_name || taskConfig.name)}"`;
  } else {
    const modifier = resolveDayModifier(taskConfig.modifier, targetDay);
    dataAttrs = `data-type="shift" data-modalities='${JSON.stringify(taskConfig.modalities || [])}' data-shift="${escapeHtml(taskConfig.shift || 'Fruehdienst')}" data-skills='${JSON.stringify(taskConfig.skill_overrides || {})}' data-modifier="${modifier}"`;
  }
  const fallbackOption = `<option value="${escapedName}" ${dataAttrs} selected>${escapedLabel}</option>`;
  return `${baseHtml}${fallbackOption}`;
}

function renderGapOptions(selectedValue = '', targetDay = null) {
  const effectiveTargetDay = targetDay || getTargetWeekdayName(currentTab);
  const gaps = getGapTasks().filter(t => isGapAvailableForDay(t, effectiveTargetDay));
  let html = '<option value="">-- Select --</option>';
  gaps.forEach(t => {
    const gapBlocks = resolveGapBlocksForTask(t, effectiveTargetDay);
    gapBlocks.forEach(gapBlock => {
      const optionTask = buildGapTaskOptionConfig(t, effectiveTargetDay, gapBlock);
      const selected = optionTask.name === selectedValue ? 'selected' : '';
      const label = optionTask.display_name || optionTask.persisted_name || optionTask.name;
      html += `<option value="${escapeHtml(optionTask.name)}" ${selected}>${escapeHtml(label)}</option>`;
    });
  });
  if (selectedValue && !gaps.some(t => t.name === selectedValue)) {
    html += `<option value="${escapeHtml(selectedValue)}" selected>${escapeHtml(selectedValue)}</option>`;
  }
  return html;
}

// Get CSS class for skill value display
function getSkillClass(value) {
  const v = normalizeSkillValueJS(value);
  switch (v) {
    case 1: return 'skill-val-1';
    case 0: return 'skill-val-0';
    case -1: return 'skill-val--1';
    case 'w': return 'skill-val-w';
    default: return '';
  }
}

function getSkillBorderClass(value) {
  const v = normalizeSkillValueJS(value);
  switch (v) {
    case 1: return 'skill-border-1';
    case 0: return 'skill-border-0';
    case -1: return 'skill-border--1';
    case 'w': return 'skill-border-w';
    default: return '';
  }
}

// Get color for skill value from shared config/fallback palette
function getSkillColor(value) {
  const v = normalizeSkillValueJS(value);
  if (v === 1) return SKILL_VALUE_COLORS.active?.color || '#28a745';
  if (v === 'w') return SKILL_VALUE_COLORS.weighted?.color || '#007bff';
  if (v === -1) return SKILL_VALUE_COLORS.excluded?.color || '#dc3545';
  return SKILL_VALUE_COLORS.passive?.color || '#856404';
}

// Calculate aggregated proficiency class for a set of values
// Priority: Positive (1) values lead the coloring over negative (-1) values
function getAggregatedClass(values) {
  if (!values || values.length === 0) return 'agg-mixed';

  const normalized = values.map(v => normalizeSkillValueJS(v));
  const allOne = normalized.every(v => v === 1 || isWeightedSkill(v));  // Include weighted/freshman
  const anyOne = normalized.some(v => v === 1 || isWeightedSkill(v));
  const allZero = normalized.every(v => v === 0);
  const anyZero = normalized.some(v => v === 0);
  const allNeg = normalized.every(v => v === -1);

  // Positive values take priority - if any positive, show green colors
  if (allOne) return 'agg-all-1';
  if (anyOne) return 'agg-any-1';  // Any positive wins over negatives
  if (allZero) return 'agg-all-0';
  if (anyZero) return 'agg-any-0';
  if (allNeg) return 'agg-all-neg';
  return 'agg-mixed';
}

// Get display value for aggregated cell
function getAggregatedDisplay(values) {
  if (!values || values.length === 0) return '-';
  const normalized = values.map(v => normalizeSkillValueJS(v));
  const allSame = normalized.every(v => v === normalized[0]);
  if (allSame) return displaySkillValue(normalized[0]);
  // Show unique values sorted (w/1, 0, -1)
  const unique = [...new Set(normalized)].sort((a, b) => {
    const aVal = isWeightedSkill(a) ? 1 : a;
    const bVal = isWeightedSkill(b) ? 1 : b;
    return bVal - aVal;
  });
  return unique.map(displaySkillValue).join('/');
}

// Check if values contain weighted entries (skill='w')
function hasWeightedEntries(values) {
  return values && values.some(v => isWeightedSkill(v));
}

// Utility: Escape HTML to prevent XSS
function escapeHtml(text) {
  if (text === null || text === undefined) return '';
  const div = document.createElement('div');
  div.textContent = String(text);
  return div.innerHTML;
}

function getPendingChangeUnits(change) {
  if (!change) return 0;
  if (change.isDelete) {
    return 1;
  }
  const updateCount = Object.keys(change.updates || {}).length;
  return updateCount > 0 ? updateCount : 1;
}

function getPendingChangeCount(tab) {
  const changes = Object.values(pendingChanges[tab] || {});
  return changes.reduce((total, change) => total + getPendingChangeUnits(change), 0);
}

function normalizeEditPlanSkillMap(skillMap = {}) {
  const normalized = {};
  SKILLS.forEach(skill => {
    normalized[skill] = normalizeSkillValueJS(skillMap?.[skill]);
  });
  return normalized;
}

function normalizeEditPlanShiftForComparison(shift = {}) {
  const rowType = shift.row_type || (shift.is_gap_entry ? 'gap' : 'shift');
  const normalizedModalities = {};
  Object.keys(shift.modalities || {}).sort().forEach(modKey => {
    const modData = shift.modalities?.[modKey] || {};
    if (isSyntheticEmptyEditPlanModality(modData)) return;
    normalizedModalities[modKey] = {
      row_index: typeof modData.row_index === 'number' ? modData.row_index : -1,
      baseSkills: normalizeEditPlanSkillMap(modData.baseSkills || modData.skills || {}),
      skills: normalizeEditPlanSkillMap(modData.skills || modData.baseSkills || {}),
    };
  });

  return {
    start_time: shift.start_time || '',
    end_time: shift.end_time || '',
    modifier: parseFloat(shift.modifier) || 1.0,
    counts_for_hours: shift.counts_for_hours !== false,
    training: shift.training !== false,
    task: shift.task || '',
    row_type: rowType,
    is_gap_entry: rowType === 'gap' || Boolean(shift.is_gap_entry),
    modalities: normalizedModalities,
  };
}

function normalizeEditPlanShiftsForComparison(shifts = []) {
  return (shifts || []).map(shift => normalizeEditPlanShiftForComparison(shift));
}

function countSkillMapChanges(beforeSkills = {}, afterSkills = {}) {
  let count = 0;
  SKILLS.forEach(skill => {
    const before = normalizeSkillValueJS(beforeSkills?.[skill]);
    const after = normalizeSkillValueJS(afterSkills?.[skill]);
    if (before !== after) {
      count += 1;
    }
  });
  return count;
}

function countEditPlanShiftChanges(beforeShift = null, afterShift = null) {
  if (!beforeShift || !afterShift) return 1;

  let count = 0;
  ['start_time', 'end_time', 'modifier', 'counts_for_hours', 'training', 'task', 'row_type'].forEach(field => {
    if (beforeShift[field] !== afterShift[field]) {
      count += 1;
    }
  });

  const modalityKeys = new Set([
    ...Object.keys(beforeShift.modalities || {}),
    ...Object.keys(afterShift.modalities || {}),
  ]);
  modalityKeys.forEach(modKey => {
    const beforeMod = beforeShift.modalities?.[modKey] || null;
    const afterMod = afterShift.modalities?.[modKey] || null;
    if (!beforeMod || !afterMod) {
      count += 1;
      return;
    }
    if (beforeMod.row_index !== afterMod.row_index) {
      count += 1;
    }
    count += countSkillMapChanges(beforeMod.baseSkills || beforeMod.skills || {}, afterMod.baseSkills || afterMod.skills || {});
  });

  return count;
}

function getEditPlanPendingChangeCount() {
  if (!currentEditEntry || !editPlanDraft || editPlanDraft.worker !== currentEditEntry.worker) {
    return 0;
  }

  const group = entriesData[currentEditEntry.tab]?.[currentEditEntry.groupIdx];
  if (!group) return 0;

  const sourceShifts = normalizeEditPlanShiftsForComparison(getTableShifts(group));
  const draftShifts = normalizeEditPlanShiftsForComparison(editPlanDraft.shifts || []);
  const maxLength = Math.max(sourceShifts.length, draftShifts.length);
  let count = 0;
  for (let idx = 0; idx < maxLength; idx += 1) {
    count += countEditPlanShiftChanges(sourceShifts[idx] || null, draftShifts[idx] || null);
  }
  return count;
}

function hasEditPlanPendingChanges() {
  return getEditPlanPendingChangeCount() > 0;
}

// Update the save button text to reflect pending change count
function updateSaveButtonCount(tab) {
  const count = getPendingChangeCount(tab);
  const saveBtn = document.getElementById(`save-inline-btn-${tab}`);
  if (saveBtn) {
    saveBtn.textContent = count > 0 ? `Save ${count} change${count !== 1 ? 's' : ''}` : 'Save Changes';
  }
}

// Helper functions for modality colors (from config)
function getModalityColor(modKey) {
  const settings = MODALITY_SETTINGS[modKey];
  return settings?.nav_color || '#6c757d';
}

function getModalityBgColor(modKey) {
  const settings = MODALITY_SETTINGS[modKey];
  return settings?.background_color || '#f8f9fa';
}
