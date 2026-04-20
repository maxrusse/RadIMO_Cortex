/**
 * Shared timeline feed builder
 * Normalizes raw modality rows into grouped worker shifts and canonical
 * timeline entries for both prep pages and the timetable page.
 */

const TimelineFeed = (function() {
  const WEIGHTED_MARKERS = new Set(['w', 'W', 2, '2']);
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

  function getModalitiesList(modalities) {
    if (Array.isArray(modalities)) return modalities.map(mod => String(mod).toLowerCase());
    if (modalities && typeof modalities === 'object') return Object.keys(modalities).map(mod => String(mod).toLowerCase());
    return [];
  }

  function normalizeSkillValue(value, normalizeFn) {
    if (typeof normalizeFn === 'function') return normalizeFn(value);
    if (value === undefined || value === null) return 0;
    if (WEIGHTED_MARKERS.has(value)) return 'w';
    if (typeof value === 'string' && value.trim() === '') return 0;
    const parsed = parseInt(value, 10);
    return Number.isNaN(parsed) ? value : parsed;
  }

  function isWeightedSkill(value) {
    return WEIGHTED_MARKERS.has(value);
  }

  function isActiveSkillValue(value) {
    const normalized = normalizeSkillValue(value);
    if (isWeightedSkill(normalized)) return true;
    return normalized === 1;
  }

  function buildWorkerSortKey(name) {
    return window.WorkerNameUtils.buildSortKey(name);
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

  function getShiftTimes(taskConfig, targetDay) {
    const defaultTimes = { start: '07:00', end: '15:00' };
    if (!taskConfig) return defaultTimes;

    const timeStr = resolveDayTimes(taskConfig.times, targetDay) || '07:00-15:00';
    if (typeof timeStr !== 'string') return defaultTimes;
    const [start, end] = timeStr.split('-');
    return { start: start?.trim() || '07:00', end: end?.trim() || '15:00' };
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
    const dayTimes = resolveDayTimes(times, targetDay);
    if (Array.isArray(dayTimes)) return parseDayTimes(dayTimes[0]);
    return parseDayTimes(dayTimes);
  }

  function isGapTask(taskName, taskRoles) {
    if (!taskName) return false;
    const taskLower = String(taskName).toLowerCase().trim();
    return (taskRoles || []).some(task => {
      if (task.type !== 'gap' || !task.name) return false;
      return String(task.name).toLowerCase().trim() === taskLower;
    });
  }

  function normalizeRowsByModality(data, modalities) {
    const result = {};
    modalities.forEach(mod => {
      result[mod] = [];
    });

    if (Array.isArray(data)) {
      data.forEach(row => {
        const mod = String(row?._modality || row?.modality || '').toLowerCase();
        if (!mod) return;
        if (!result[mod]) result[mod] = [];
        result[mod].push(row);
      });
      return result;
    }

    if (data && typeof data === 'object') {
      Object.entries(data).forEach(([modality, rows]) => {
        const mod = String(modality || '').toLowerCase();
        result[mod] = Array.isArray(rows) ? rows : [];
      });
    }

    return result;
  }

  function getTableShifts(group) {
    if (!group) return [];
    return group.tableShiftsArray || group.modalShiftsArray || group.shiftsArray || [];
  }

  function buildEntriesByWorker(data, options = {}) {
    const modalities = getModalitiesList(options.modalities);
    const skills = Array.isArray(options.skills) ? options.skills : [];
    const workerSkills = options.workerSkills || {};
    const taskRoles = Array.isArray(options.taskRoles) ? options.taskRoles : [];
    const targetDay = options.targetDay || null;
    const lastAddedShiftMeta = options.lastAddedShiftMeta || null;
    const normalizeFn = options.normalizeSkillValue;

    const counts = {};
    const grouped = {};
    const rowsByModality = normalizeRowsByModality(data, modalities);

    modalities.forEach(mod => {
      const modData = Array.isArray(rowsByModality[mod]) ? rowsByModality[mod] : [];
      modData.forEach(row => {
        const workerName = row.PPL;
        if (!workerName) return;
        counts[workerName] = (counts[workerName] || 0) + 1;

        let taskStr = row.tasks || '';
        let taskParts = [];
        if (Array.isArray(taskStr)) {
          taskParts = taskStr.filter(task => task && task.trim());
          taskStr = taskParts.join(', ');
        } else {
          taskParts = String(taskStr)
            .split(',')
            .map(task => task.trim())
            .filter(Boolean);
        }

        const rowType = row.row_type || 'shift';
        const normalizedRowType = rowType.toString().toLowerCase();
        const isGapRow = normalizedRowType === 'gap' || normalizedRowType === 'gap_segment';
        const training = row.training === undefined || row.training === null
          ? !isGapRow
          : !(row.training === false || row.training === 0 || row.training === '0' || String(row.training).trim().toLowerCase() === 'false');

        let roleConfig = taskRoles.find(task => task.name === taskStr);
        if (isGapRow && !roleConfig && taskParts.length > 0) {
          const gapTaskName = taskParts.find(task => isGapTask(task, taskRoles));
          if (gapTaskName) {
            roleConfig = taskRoles.find(task => task.name === gapTaskName);
          }
        }

        let startTime = row.start_time;
        let endTime = row.end_time;
        if ((!startTime || !endTime) && roleConfig) {
          if (isGapRow) {
            const parsedTimes = getGapTimeRange(roleConfig, targetDay);
            if (parsedTimes) {
              [startTime, endTime] = parsedTimes;
            }
          } else {
            const shiftTimes = getShiftTimes(roleConfig, targetDay);
            startTime = startTime || shiftTimes.start;
            endTime = endTime || shiftTimes.end;
          }
        }
        if (!startTime || !endTime) {
          [startTime, endTime] = isGapRow ? ['12:00', '13:00'] : ['07:00', '15:00'];
        }

        const rosterPreset = workerSkills[workerName] || {};
        const rosterSkills = rosterPreset[mod] || {};

        let countsForHours = row.counts_for_hours;
        if (countsForHours === undefined) {
          countsForHours = roleConfig ? roleConfig.counts_for_hours : true;
        }

        const entry = {
          worker: workerName,
          modality: mod,
          row_index: row.row_index,
          start_time: startTime,
          end_time: endTime,
          modifier: row.Modifier !== undefined ? row.Modifier : 1.0,
          counts_for_hours: countsForHours !== false,
          is_gap_entry: isGapRow,
          row_type: isGapRow ? 'gap_segment' : 'shift_segment',
          training,
          skills: skills.reduce((acc, skill) => {
            const rawVal = row[skill];
            const hasRaw = rawVal !== undefined && rawVal !== '';
            if (isGapRow) {
              if (hasRaw) {
                acc[skill] = normalizeSkillValue(rawVal, normalizeFn);
                return acc;
              }
              const overrides = roleConfig?.skill_overrides || {};
              const skillModKey = `${skill}_${mod}`;
              if (overrides[skillModKey] !== undefined) {
                acc[skill] = normalizeSkillValue(overrides[skillModKey], normalizeFn);
                return acc;
              }
              if (overrides[skill] !== undefined) {
                acc[skill] = normalizeSkillValue(overrides[skill], normalizeFn);
                return acc;
              }
              if (overrides.all !== undefined) {
                acc[skill] = normalizeSkillValue(overrides.all, normalizeFn);
                return acc;
              }
              acc[skill] = -1;
              return acc;
            }

            const fallback = rosterSkills[skill];
            const hasFallback = fallback !== undefined && fallback !== '';

            const normalizedRaw = hasRaw ? normalizeSkillValue(rawVal, normalizeFn) : undefined;
            const normalizedFallback = hasFallback ? normalizeSkillValue(fallback, normalizeFn) : undefined;

            acc[skill] = hasRaw
              ? normalizedRaw
              : (hasFallback ? normalizedFallback : 0);
            return acc;
          }, {}),
          task: taskStr
        };

        if (!grouped[workerName]) {
          grouped[workerName] = {
            worker: workerName,
            shifts: {},
            modalShifts: {},
            allEntries: [],
            allGaps: []
          };
        }

        grouped[workerName].allEntries.push(entry);
        const gapCandidates = isGapRow ? [{
          start: startTime,
          end: endTime,
          activity: taskStr,
          counts_for_hours: countsForHours === true
        }] : [];
        grouped[workerName].allGaps = [...(grouped[workerName].allGaps || []), ...gapCandidates];

        const taskKey = (entry.task || '').trim();
        const shiftKey = entry.is_gap_entry
          ? `${entry.start_time}-${entry.end_time}-gap-${taskKey}`
          : `${entry.start_time}-${entry.end_time}`;
        const modalShiftKey = `${entry.start_time}-${entry.end_time}-${entry.is_gap_entry ? 'gap' : 'shift'}-${taskKey}`;

        if (!grouped[workerName].shifts[shiftKey]) {
          grouped[workerName].shifts[shiftKey] = {
            start_time: entry.start_time,
            end_time: entry.end_time,
            modifier: entry.modifier,
            counts_for_hours: entry.counts_for_hours,
            task: entry.task,
            modalities: {},
            timeSegments: [{ start: entry.start_time, end: entry.end_time }],
            is_gap_entry: entry.is_gap_entry,
            row_type: entry.row_type
          };
        }
        if (!grouped[workerName].modalShifts[modalShiftKey]) {
          grouped[workerName].modalShifts[modalShiftKey] = {
            start_time: entry.start_time,
            end_time: entry.end_time,
            modifier: entry.modifier,
            counts_for_hours: entry.counts_for_hours,
            task: entry.task,
            modalities: {},
            timeSegments: [{ start: entry.start_time, end: entry.end_time }],
            is_gap_entry: entry.is_gap_entry,
            row_type: entry.row_type
          };
        }

        grouped[workerName].shifts[shiftKey].modalities[mod] = {
          skills: entry.skills,
          row_index: entry.row_index,
          modifier: entry.modifier
        };
        grouped[workerName].modalShifts[modalShiftKey].modalities[mod] = {
          skills: entry.skills,
          row_index: entry.row_index,
          modifier: entry.modifier
        };

        const existingTask = grouped[workerName].shifts[shiftKey].task;
        if (entry.task && existingTask && !existingTask.includes(entry.task)) {
          grouped[workerName].shifts[shiftKey].task = `${existingTask}, ${entry.task}`;
        } else if (entry.task && !existingTask) {
          grouped[workerName].shifts[shiftKey].task = entry.task;
        }
        if (grouped[workerName].shifts[shiftKey].is_gap_entry !== undefined) {
          grouped[workerName].shifts[shiftKey].is_gap_entry =
            grouped[workerName].shifts[shiftKey].is_gap_entry && entry.is_gap_entry;
        }

        const existingModalTask = grouped[workerName].modalShifts[modalShiftKey].task;
        if (entry.task && existingModalTask && !existingModalTask.includes(entry.task)) {
          grouped[workerName].modalShifts[modalShiftKey].task = `${existingModalTask}, ${entry.task}`;
        } else if (entry.task && !existingModalTask) {
          grouped[workerName].modalShifts[modalShiftKey].task = entry.task;
        }
      });
    });

    Object.values(grouped).forEach(group => {
      const preset = workerSkills[group.worker] || {};
      Object.values(group.shifts).forEach(shift => {
        modalities.forEach(modKey => {
          if (!shift.modalities[modKey]) {
            const skillsByModality = {};
            const rosterDefaults = preset[modKey] || {};
            skills.forEach(skill => {
              const fallback = rosterDefaults[skill];
              skillsByModality[skill] = fallback !== undefined ? fallback : -1;
            });
            shift.modalities[modKey] = {
              skills: skillsByModality,
              row_index: -1,
              modifier: shift.modifier || 1.0,
              placeholder: true
            };
          }
        });
      });
    });

    Object.values(grouped).forEach(group => {
      const shiftsArr = Object.entries(group.shifts)
        .map(([key, shift]) => ({ ...shift, shiftKey: key }))
        .sort((a, b) => (a.start_time || '').localeCompare(b.start_time || ''));

      let modalShiftsArr = Object.entries(group.modalShifts || {})
        .map(([key, shift]) => ({ ...shift, shiftKey: key }))
        .sort((a, b) => (a.start_time || '').localeCompare(b.start_time || ''));

      if (lastAddedShiftMeta && lastAddedShiftMeta.worker === group.worker) {
        const matchIdx = modalShiftsArr.findIndex(shift => shift.shiftKey === lastAddedShiftMeta.shiftKey);
        if (matchIdx >= 0) {
          const [match] = modalShiftsArr.splice(matchIdx, 1);
          modalShiftsArr.push(match);
        }
      }

      group.modalShiftsArray = modalShiftsArr.map(shift => {
        const segments = (shift.timeSegments || []).sort((a, b) => (a.start || '').localeCompare(b.start || ''));
        const firstStart = segments[0]?.start || shift.start_time;
        const lastEnd = segments[segments.length - 1]?.end || shift.end_time;
        return {
          ...shift,
          start_time: firstStart,
          end_time: lastEnd,
          timeSegments: segments
        };
      });

      const mergedShifts = [];
      let currentMerged = null;
      shiftsArr.forEach(shift => {
        if (!currentMerged) {
          currentMerged = {
            ...shift,
            timeSegments: [{ start: shift.start_time, end: shift.end_time }],
            is_gap_entry: shift.is_gap_entry,
            row_type: shift.row_type
          };
        } else {
          mergedShifts.push(currentMerged);
          currentMerged = {
            ...shift,
            timeSegments: [{ start: shift.start_time, end: shift.end_time }],
            is_gap_entry: shift.is_gap_entry,
            row_type: shift.row_type
          };
        }
      });
      if (currentMerged) mergedShifts.push(currentMerged);

      group.shiftsArray = mergedShifts.map(shift => {
        const segments = (shift.timeSegments || []).sort((a, b) => (a.start || '').localeCompare(b.start || ''));
        const firstStart = segments[0]?.start || shift.start_time;
        const lastEnd = segments[segments.length - 1]?.end || shift.end_time;
        return {
          ...shift,
          start_time: firstStart,
          end_time: lastEnd,
          timeSegments: segments
        };
      });

      group.tableShiftsArray = group.modalShiftsArray || group.shiftsArray;
    });

    const entries = Object.values(grouped).sort((a, b) => {
      const aShift = getTableShifts(a)[0] || {};
      const bShift = getTableShifts(b)[0] || {};
      const aTime = aShift.start_time || '';
      const bTime = bShift.start_time || '';
      const timeCmp = aTime.localeCompare(bTime);
      if (timeCmp !== 0) return timeCmp;

      const aTask = aShift.task || '';
      const bTask = bShift.task || '';
      const taskCmp = aTask.localeCompare(bTask);
      if (taskCmp !== 0) return taskCmp;

      return buildWorkerSortKey(a.worker || '').localeCompare(buildWorkerSortKey(b.worker || ''));
    });

    return { entries, counts };
  }

  function convertGroupsToTimelineData(groups, options = {}) {
    const skills = Array.isArray(options.skills) ? options.skills : [];
    const normalizeFn = options.normalizeSkillValue;
    const timelineEntries = [];

    (groups || []).forEach(group => {
      const worker = (group.worker || '').trim();
      const shifts = getTableShifts(group).filter(shift => !shift.deleted);
      shifts.forEach(shift => {
        const isGapRow = Boolean(shift.is_gap_entry);
        const assignedModalities = Object.entries(shift.modalities || {})
          .filter(([_, modData]) => modData.row_index !== undefined && modData.row_index >= 0);

        const entry = {
          PPL: worker,
          worker,
          start_time: shift.start_time,
          end_time: shift.end_time,
          TIME: `${shift.start_time}-${shift.end_time}`,
          modalities: [],
          row_type: isGapRow ? 'gap_segment' : 'shift_segment',
          training: shift.training !== false,
          tasks: shift.task ? [shift.task] : [],
          activeSkillsByModality: {},
          explicitSkillsByModality: {},
          explicitSkillValues: {}
        };

        if (!isGapRow) {
          assignedModalities.forEach(([modKey, modData]) => {
            const mod = String(modKey || '').toUpperCase();
            if (!mod) return;
            entry.activeSkillsByModality[mod] = entry.activeSkillsByModality[mod] || {};
            entry.explicitSkillsByModality[mod] = entry.explicitSkillsByModality[mod] || {};

            skills.forEach(skill => {
              const val = modData.skills?.[skill];
              const normalized = normalizeSkillValue(val, normalizeFn);
              const isActive = isWeightedSkill(normalized) || normalized >= 1;
              const isExplicit = normalized === 1;

              if (isActive) {
                entry.activeSkillsByModality[mod][skill] = 1;
              }
              if (isExplicit) {
                entry.explicitSkillsByModality[mod][skill] = 1;
              }
            });
          });
        }

        entry.modalities = Object.entries(entry.activeSkillsByModality)
          .filter(([_, skillMap]) => Object.keys(skillMap || {}).length > 0)
          .map(([modKey]) => modKey.toLowerCase());

        skills.forEach(skill => {
          const isActive = Object.values(entry.activeSkillsByModality).some(modSkills => modSkills?.[skill] === 1);
          const isExplicit = Object.values(entry.explicitSkillsByModality).some(modSkills => modSkills?.[skill] === 1);
          entry[skill] = isActive ? 1 : 0;
          if (isExplicit) {
            entry.explicitSkillValues[skill] = 1;
          }
        });

        timelineEntries.push(entry);
      });
    });

    return timelineEntries;
  }

  return {
    buildEntriesByWorker,
    convertGroupsToTimelineData
  };
})();
