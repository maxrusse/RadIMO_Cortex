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
const GERMAN_WEEKDAYS = ['Sonntag', 'Montag', 'Dienstag', 'Mittwoch', 'Donnerstag', 'Freitag', 'Samstag'];
const ENGLISH_TO_GERMAN_WEEKDAYS = {
  sunday: 'Sonntag',
  monday: 'Montag',
  tuesday: 'Dienstag',
  wednesday: 'Mittwoch',
  thursday: 'Donnerstag',
  friday: 'Freitag',
  saturday: 'Samstag'
};
const GERMAN_TO_ENGLISH_WEEKDAYS = {
  Sonntag: 'sunday',
  Montag: 'monday',
  Dienstag: 'tuesday',
  Mittwoch: 'wednesday',
  Donnerstag: 'thursday',
  Freitag: 'friday',
  Samstag: 'saturday'
};
const WORKER_SORT_TITLES = new Set(['dr', 'pd', 'prof', 'med', 'dent', 'dipl', 'ing', 'dipl-ing']);
const WORKER_SORT_PARTICLES = new Set(['von', 'van', 'de', 'del', 'der', 'den', 'zu', 'zum', 'zur']);
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
  const raw = (name == null ? '' : String(name)).trim();
  if (!raw) return '';

  const cleaned = raw.replace(/\s*\([^)]*\)\s*$/, '').replace(/\s+/g, ' ').trim();
  if (!cleaned) return raw.toLowerCase();

  const tokens = cleaned
    .split(' ')
    .map(token => token.trim().replace(/^[,.;:()[\]{}]+|[,.;:()[\]{}]+$/g, ''))
    .filter(Boolean)
    .filter(token => {
      const normalized = token.toLowerCase();
      return !WORKER_SORT_TITLES.has(normalized) && !WORKER_SORT_PARTICLES.has(normalized);
    });

  if (tokens.length === 0) {
    const fallback = cleaned.toLowerCase();
    return `${fallback}|${fallback}`;
  }

  const last = tokens[tokens.length - 1].toLowerCase();
  const first = tokens.slice(0, -1).join(' ').toLowerCase();
  const full = tokens.join(' ').toLowerCase();
  return `${last}|${first}|${full}`;
}


/**
 * Parse worker input like "Dr. Name (ID)" or just "ID".
 * Returns { id, fullName } where id is the canonical worker ID.
 */
function parseWorkerInput(inputValue) {
  const trimmed = (inputValue || '').trim();
  // Match pattern: "anything (ID)" where ID is inside parentheses
  const match = trimmed.match(/^(.+?)\s*\(([^)]+)\)$/);
  if (match) {
    return { id: match[2].trim(), fullName: trimmed };
  }
  // No parentheses - treat as plain ID
  return { id: trimmed, fullName: null };
}

/**
 * Get display name for a worker ID.
 * Returns "Full Name (ID)" format if name is known, otherwise just the ID.
 */
function getWorkerDisplayName(workerId) {
  const fullName = WORKER_NAMES[workerId];
  if (fullName && fullName !== workerId) {
    // If full name already contains the ID in parentheses, use it as-is
    if (fullName.includes('(' + workerId + ')')) {
      return fullName;
    }
    // Otherwise, append ID in parentheses
    return fullName + ' (' + workerId + ')';
  }
  return workerId;
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

function normalizeWeekdayName(targetDay) {
  if (!targetDay || typeof targetDay !== 'string') return targetDay;
  const normalized = targetDay.trim().toLowerCase();
  return ENGLISH_TO_GERMAN_WEEKDAYS[normalized] || targetDay;
}

function resolveDayTimes(timesConfig, targetDay) {
  const times = timesConfig || {};
  if (Object.keys(times).length === 0) return null;
  const normalizedDay = normalizeWeekdayName(targetDay);
  if (normalizedDay && times[normalizedDay]) return times[normalizedDay];
  const englishDay = GERMAN_TO_ENGLISH_WEEKDAYS[normalizedDay];
  if (englishDay && times[englishDay]) return times[englishDay];
  return times.default || null;
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
  const sourceShifts = group.modalShiftsArray || group.shiftsArray || [];
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

function updateEditPlanDraftShiftSkill(shiftIdx, modKey, skill, value, trainingEnabled = null) {
  if (!editPlanDraft || !editPlanDraft.shifts) return null;
  const shift = editPlanDraft.shifts[shiftIdx];
  if (!shift || !shift.modalities || !shift.modalities[modKey]) return null;
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
  const gapTasks = getGapTasks();
  const taskLower = taskName.toLowerCase().trim();
  return gapTasks.some(g => g.name && g.name.toLowerCase().trim() === taskLower);
}

// Cache for pre-built dropdown options (performance optimization)
// Key format: targetDay -> { baseHtmlNoGaps, baseHtmlWithGaps, optionsByValue, firstShiftName }
let taskOptionsCacheByDay = new Map();

function isGapAvailableForDay(taskConfig, targetDay) {
  if (!taskConfig || taskConfig.type !== 'gap') return true;
  const times = taskConfig.times || {};
  if (Object.keys(times).length === 0) return true;
  return Boolean(resolveDayTimes(times, targetDay));
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

  // Regular shifts group
  if (shifts.length > 0) {
    const optgroupStart = '<optgroup label="Shifts">';
    const optgroupEnd = '</optgroup>';
    baseHtmlNoGaps += optgroupStart;
    baseHtmlWithGaps += optgroupStart;

    shifts.forEach(t => {
      const escapedName = escapeHtml(t.name);
      const dataAttrs = `data-type="shift" data-modalities='${JSON.stringify(t.modalities || [])}' data-shift="${escapeHtml(t.shift || 'Fruehdienst')}" data-skills='${JSON.stringify(t.skill_overrides || {})}' data-modifier="${t.modifier || 1.0}"`;
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
      const dataAttrs = `data-type="shift" data-modalities='${JSON.stringify(t.modalities || [])}' data-shift="${escapeHtml(t.shift || 'Fruehdienst')}" data-skills='${JSON.stringify(t.skill_overrides || {})}' data-modifier="${t.modifier || 1.0}" data-counts-for-hours="false"`;
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
      const escapedName = escapeHtml(t.name);
      const dataAttrs = `data-type="gap" data-times='${JSON.stringify(t.times || {})}'`;
      const optionHtml = `<option value="${escapedName}" ${dataAttrs}>${escapedName}</option>`;
      const optionHtmlSelected = `<option value="${escapedName}" ${dataAttrs} selected>${escapedName}</option>`;

      baseHtmlWithGaps += optionHtml;
      optionsByValue.set(t.name, { html: optionHtml, htmlSelected: optionHtmlSelected, isShift: false });
    });
    baseHtmlWithGaps += '</optgroup>';
  }

  // Get first shift name for autoSelectFirst feature
  const firstShiftName = shifts.length > 0 ? shifts[0].name : (blockerShifts.length > 0 ? blockerShifts[0].name : null);

  const taskOptionsCache = {
    baseHtmlNoGaps,
    baseHtmlWithGaps,
    optionsByValue,
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
function renderTaskOptionsWithGroups(selectedValue = '', includeGaps = false, autoSelectFirst = false, targetDay = null) {
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

  // Selected value not found in cache, add a fallback option to preserve existing value
  if (!selectedValue) {
    return baseHtml;
  }
  const taskConfig = TASK_ROLES.find(t => t.name === selectedValue);
  if (!taskConfig) {
    return baseHtml;
  }
  const escapedName = escapeHtml(taskConfig.name);
  let dataAttrs = '';
  if (taskConfig.type === 'gap') {
    dataAttrs = `data-type="gap" data-times='${JSON.stringify(taskConfig.times || {})}'`;
  } else {
    dataAttrs = `data-type="shift" data-modalities='${JSON.stringify(taskConfig.modalities || [])}' data-shift="${escapeHtml(taskConfig.shift || 'Fruehdienst')}" data-skills='${JSON.stringify(taskConfig.skill_overrides || {})}' data-modifier="${taskConfig.modifier || 1.0}"`;
  }
  const fallbackOption = `<option value="${escapedName}" ${dataAttrs} selected>${escapedName}</option>`;
  return `${baseHtml}${fallbackOption}`;
}

function renderGapOptions(selectedValue = '', targetDay = null) {
  const effectiveTargetDay = targetDay || getTargetWeekdayName(currentTab);
  const gaps = getGapTasks().filter(t => isGapAvailableForDay(t, effectiveTargetDay));
  let html = '<option value="">-- Select --</option>';
  gaps.forEach(t => {
    const selected = t.name === selectedValue ? 'selected' : '';
    html += `<option value="${escapeHtml(t.name)}" ${selected}>${escapeHtml(t.name)}</option>`;
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

// Get color for skill value - only 1 and w get strong colors, 0/-1 are neutral (from config)
function getSkillColor(value) {
  const v = normalizeSkillValueJS(value);
  if (v === 1) return SKILL_VALUE_COLORS.active?.color || '#28a745';
  if (v === 'w') return SKILL_VALUE_COLORS.weighted?.color || '#17a2b8';
  if (v === -1) return SKILL_VALUE_COLORS.excluded?.color || '#ccc';
  return SKILL_VALUE_COLORS.passive?.color || '#ccc';
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

// Update the save button text to reflect pending change count
function updateSaveButtonCount(tab) {
  const changes = Object.values(pendingChanges[tab] || {});
  const count = changes.reduce((total, change) => {
    if (change.isDelete || change.isNew) {
      return total + 1;
    }
    const updateCount = Object.keys(change.updates || {}).length;
    return total + (updateCount > 0 ? updateCount : 1);
  }, 0);
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
