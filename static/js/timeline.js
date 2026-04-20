/**
 * Shared Timeline Chart Module
 * Used by both timetable.html and prep_next_day.html
 */

const TimelineChart = (function() {
  // Default timeline config
  const TIMELINE_START = 6;  // 6:00
  const TIMELINE_END = 20;   // 20:00
  const TIMELINE_HOURS = TIMELINE_END - TIMELINE_START;

  // Parse time string "HH:MM" into hours and minutes
  function parseTimeStr(timeStr) {
    if (!timeStr || typeof timeStr !== 'string') return null;
    const parts = timeStr.split(':');
    if (parts.length < 2) return null;
    const [h, m] = parts.map(Number);
    return { hours: h || 0, minutes: m || 0 };
  }

  // Convert time string to minutes for comparison
  function timeToMinutes(timeStr) {
    const parsed = parseTimeStr(timeStr);
    if (!parsed) return 0;
    return parsed.hours * 60 + parsed.minutes;
  }

  // Convert time string to percentage position
  function timeToPercent(timeStr) {
    const parsed = parseTimeStr(timeStr);
    if (!parsed) return 0;
    const hours = parsed.hours + parsed.minutes / 60;
    const clamped = Math.max(TIMELINE_START, Math.min(TIMELINE_END, hours));
    return ((clamped - TIMELINE_START) / TIMELINE_HOURS) * 100;
  }

  // Check if skill is active (value >= 1 or weighted)
  function isSkillActive(val) {
    if (val === 'w' || val === 'W') return true;
    const n = Number(val);
    return !isNaN(n) && n >= 1;
  }

  // Check if skill is visible (value >= 0 or weighted)
  function isSkillVisible(val) {
    if (val === 'w' || val === 'W') return true;
    if (val === '' || val === null || val === undefined) return false;
    const n = Number(val);
    return !isNaN(n) && n >= 0;
  }

  // Check if any skill in entry is active
  function hasAnyActiveSkill(entry, skillColumns) {
    const hasSkills = skillColumns.some(s => {
      const val = entry[s];
      return isSkillActive(val);
    });
    if (hasSkills) return true;
    const rowType = (entry.row_type || '').toString().toLowerCase();
    return rowType === 'gap' || rowType === 'gap_segment';
  }

  // Check if any skill in entry is visible (active or zero)
  function hasAnyVisibleSkill(entry, skillColumns) {
    const hasSkills = skillColumns.some(s => {
      const val = entry[s];
      return isSkillVisible(val);
    });
    if (hasSkills) return true;
    const rowType = (entry.row_type || '').toString().toLowerCase();
    return rowType === 'gap' || rowType === 'gap_segment';
  }

  // Check if skill is explicitly active (value === 1)
  function isSkillExplicitOne(val) {
    if (val === 1 || val === '1') return true;
    if (val === null || val === undefined) return false;
    const numeric = Number(val);
    return !Number.isNaN(numeric) && numeric === 1;
  }

  // Escape HTML for XSS protection
  function escapeHtml(text) {
    if (text == null) return '';
    const div = document.createElement('div');
    div.textContent = String(text);
    return div.innerHTML;
  }

  function buildWorkerSortKey(name) {
    return window.WorkerNameUtils.buildSortKey(name);
  }


  function normalizeTasks(rawTasks) {
    if (!rawTasks) return [];
    if (Array.isArray(rawTasks)) {
      return rawTasks.map(String).filter(t => t.trim() !== '');
    }
    if (typeof rawTasks === 'string') {
      return rawTasks.split(',').map(t => t.trim()).filter(Boolean);
    }
    return [String(rawTasks)].filter(t => t.trim() !== '');
  }

  function buildNormalizedTimelineEntry(entry, skillColumns) {
    if (!entry || typeof entry !== 'object') return entry;

    const normalized = { ...entry };
    const activeSkillsByModality = {};
    const explicitSkillsByModality = {};
    const skillValues = { ...(normalized.skillValues || {}) };
    const explicitSkillValues = { ...(normalized.explicitSkillValues || {}) };

    mergeModalitySkillMaps(activeSkillsByModality, normalized.activeSkillsByModality, isSkillActive);
    mergeModalitySkillMaps(explicitSkillsByModality, normalized.explicitSkillsByModality, isSkillExplicitOne);

    const rawModalities = normalized.modalities instanceof Set
      ? Array.from(normalized.modalities)
      : (Array.isArray(normalized.modalities) ? normalized.modalities : []);
    const fallbackModality = normalized._modality || normalized.modality || '';
    const candidateModalities = rawModalities.length > 0
      ? rawModalities.map(mod => String(mod).toUpperCase())
      : (fallbackModality ? [String(fallbackModality).toUpperCase()] : []);

    skillColumns.forEach(skill => {
      if (isSkillActive(normalized[skill]) || isSkillActive(skillValues[skill])) {
        skillValues[skill] = 1;
        candidateModalities.forEach(mod => addSkillToModalityMap(activeSkillsByModality, mod, skill));
      }
      if (isSkillExplicitOne(normalized[skill]) || isSkillExplicitOne(explicitSkillValues[skill])) {
        explicitSkillValues[skill] = 1;
        candidateModalities.forEach(mod => addSkillToModalityMap(explicitSkillsByModality, mod, skill));
      }
    });

    const activeModalities = Object.keys(activeSkillsByModality).sort();

    normalized.activeSkillsByModality = activeSkillsByModality;
    normalized.explicitSkillsByModality = explicitSkillsByModality;
    normalized.skillValues = skillValues;
    normalized.explicitSkillValues = explicitSkillValues;
    normalized.modalities = new Set(activeModalities);

    return normalized;
  }

  function ensureModalitySkillMap(mapObj, modality) {
    const key = String(modality || '').toUpperCase();
    if (!key) return null;
    if (!mapObj[key]) mapObj[key] = {};
    return mapObj[key];
  }

  function addSkillToModalityMap(mapObj, modality, skill) {
    const bucket = ensureModalitySkillMap(mapObj, modality);
    if (!bucket || !skill) return;
    bucket[skill] = 1;
  }

  function mergeModalitySkillMaps(target, source, predicate = null) {
    if (!source || typeof source !== 'object') return;
    Object.entries(source).forEach(([modality, skills]) => {
      if (!skills || typeof skills !== 'object') return;
      Object.keys(skills).forEach(skill => {
        const value = skills[skill];
        if (predicate && !predicate(value)) return;
        addSkillToModalityMap(target, modality, skill);
      });
    });
  }

  function buildTooltipModSkillLabels(entry, skillColumns, skillSlugMap) {
    const labels = [];
    const seen = new Set();
    const orderedSkills = Array.isArray(skillColumns) ? skillColumns : [];

    const pushLabel = (label) => {
      if (!label || seen.has(label)) return;
      seen.add(label);
      labels.push(label);
    };

    const activeByModality = entry.activeSkillsByModality || {};
    const modalityKeys = Object.keys(activeByModality).sort();

    modalityKeys.forEach(modality => {
      const skillMap = activeByModality[modality] || {};
      const skillSet = new Set(
        Object.keys(skillMap).filter(skill => isSkillActive(skillMap[skill]))
      );
      if (skillSet.size === 0) return;

      const ordered = orderedSkills.filter(skill => skillSet.has(skill));
      const remaining = Array.from(skillSet).filter(skill => !ordered.includes(skill)).sort();
      const allSkillsSelected = orderedSkills.length > 0
        && ordered.length === orderedSkills.length
        && remaining.length === 0;

      if (allSkillsSelected) {
        pushLabel(`${String(modality).toUpperCase()}_ALL`);
        return;
      }

      [...ordered, ...remaining].forEach(skill => {
        const slug = skillSlugMap[skill] || String(skill).toLowerCase();
        pushLabel(`${String(modality).toUpperCase()}_${slug}`);
      });
    });

    // Fallback for older entries without activeSkillsByModality.
    if (labels.length === 0 && entry.skillValues) {
      const mod = entry._modality || entry.modality
        || (entry.modalities && entry.modalities.size === 1 ? Array.from(entry.modalities)[0] : '');
      if (mod) {
        const activeSkills = Object.keys(entry.skillValues)
          .filter(skill => isSkillActive(entry.skillValues[skill]));
        activeSkills.forEach(skill => {
          const slug = skillSlugMap[skill] || String(skill).toLowerCase();
          pushLabel(`${String(mod).toUpperCase()}_${slug}`);
        });
      }
    }

    return labels;
  }

  // Build gradient for skill stripes
  function buildSkillGradient(skills, skillColorMap) {
    if (!skills || skills.length === 0) return '#ddd';
    if (skills.length === 1) {
      const color = skillColorMap[skills[0]] || '#ccc';
      return `repeating-linear-gradient(90deg, ${color} 0, ${color} 10px, #fff 10px, #fff 25px)`;
    }
    const sw = 10, gw = 15;
    const colors = skills.map(s => skillColorMap[s] || '#ccc');
    const stops = colors.map((c, i) => `${c} ${i * sw}px, ${c} ${(i + 1) * sw}px`);
    const bw = colors.length * sw;
    stops.push(`#fff ${bw}px, #fff ${bw + gw}px`);
    return `repeating-linear-gradient(90deg, ${stops.join(', ')})`;
  }

  // Merge entries across modalities and time
  function mergeEntriesByTime(entries, skillColumns) {
    if (!entries || entries.length === 0) return [];

    const sorted = [...entries].sort((a, b) => timeToMinutes(a.start_time) - timeToMinutes(b.start_time));
    const mergedEntries = [];
    let current = null;

    const pushCurrent = () => {
      if (!current) return;
      current.TIME = `${current.start_time}-${current.end_time}`;
      current.tasks = Array.from(current.tasks);
      mergedEntries.push(current);
    };

    sorted.forEach(entry => {
      const startMin = timeToMinutes(entry.start_time);
      const endMin = timeToMinutes(entry.end_time);

      if (!current) {
        current = {
          start_time: entry.start_time,
          end_time: entry.end_time,
          TIME: entry.TIME,
          modalities: new Set(),
          skillValues: {},
          explicitSkillValues: {},
          activeSkillsByModality: {},
          explicitSkillsByModality: {},
          tasks: new Set()
        };
      } else {
        const currentEndMin = timeToMinutes(current.end_time);
        if (startMin >= currentEndMin) {
          pushCurrent();
          current = {
            start_time: entry.start_time,
            end_time: entry.end_time,
            TIME: entry.TIME,
            modalities: new Set(),
            skillValues: {},
            explicitSkillValues: {},
            activeSkillsByModality: {},
            explicitSkillsByModality: {},
            tasks: new Set()
          };
        } else if (endMin > currentEndMin) {
          current.end_time = entry.end_time;
        }
      }

      if (entry._modality && Object.keys(entry.activeSkillsByModality || {}).length === 0) {
        current.modalities.add(entry._modality.toUpperCase());
      }
      if (entry.modalities) {
        const modalList = entry.modalities instanceof Set ? Array.from(entry.modalities) : entry.modalities;
        if (Array.isArray(modalList)) {
          modalList.forEach(mod => current.modalities.add(String(mod).toUpperCase()));
        }
      }

      mergeModalitySkillMaps(current.activeSkillsByModality, entry.activeSkillsByModality, isSkillActive);
      mergeModalitySkillMaps(current.explicitSkillsByModality, entry.explicitSkillsByModality, isSkillExplicitOne);

      const fallbackModalities = entry.modalities
        ? (entry.modalities instanceof Set ? Array.from(entry.modalities) : entry.modalities)
        : [];
      const normalizedFallbackModalities = Array.isArray(fallbackModalities)
        ? fallbackModalities.map(mod => String(mod).toUpperCase())
        : [];
      const singleFallbackModality = (entry._modality || entry.modality || '').toString().toUpperCase();
      const effectiveModalities = normalizedFallbackModalities.length > 0
        ? normalizedFallbackModalities
        : (singleFallbackModality ? [singleFallbackModality] : []);

      skillColumns.forEach(s => {
        if (isSkillActive(entry[s])) {
          current.skillValues[s] = 1;
          effectiveModalities.forEach(mod => addSkillToModalityMap(current.activeSkillsByModality, mod, s));
        }
        if (isSkillExplicitOne(entry[s])) {
          current.explicitSkillValues[s] = 1;
          effectiveModalities.forEach(mod => addSkillToModalityMap(current.explicitSkillsByModality, mod, s));
        }
      });

      normalizeTasks(entry.tasks || entry.task).forEach(task => current.tasks.add(task));
    });

    pushCurrent();
    return mergedEntries;
  }

  function mergeEntriesForSingleLane(entries, skillColumns) {
    if (!entries || entries.length === 0) return [];

    const sorted = [...entries].sort((a, b) => {
      const startDiff = timeToMinutes(a.start_time) - timeToMinutes(b.start_time);
      if (startDiff !== 0) return startDiff;
      return timeToMinutes(a.end_time) - timeToMinutes(b.end_time);
    });

    const merged = [];

    sorted.forEach(entry => {
      const start = timeToMinutes(entry.start_time);
      const end = timeToMinutes(entry.end_time);

      const skillValues = {};
      const explicitSkillValues = {};
      const activeSkillsByModality = {};
      const explicitSkillsByModality = {};
      if (entry.skillValues) {
        Object.keys(entry.skillValues).forEach(s => {
          if (isSkillActive(entry.skillValues[s])) {
            skillValues[s] = 1;
          }
        });
        if (entry.explicitSkillValues) {
          Object.keys(entry.explicitSkillValues).forEach(s => {
            if (isSkillExplicitOne(entry.explicitSkillValues[s])) {
              explicitSkillValues[s] = 1;
            }
          });
        }
      } else {
        skillColumns.forEach(s => {
          if (isSkillActive(entry[s])) {
            skillValues[s] = 1;
          }
          if (isSkillExplicitOne(entry[s])) {
            explicitSkillValues[s] = 1;
          }
        });
      }

      const modalities = new Set();
      if (entry.modalities) {
        if (entry.modalities instanceof Set) {
          entry.modalities.forEach(m => modalities.add(m));
        } else if (Array.isArray(entry.modalities)) {
          entry.modalities.forEach(m => modalities.add(m));
        }
      }
      if (entry._modality || entry.modality) {
        modalities.add((entry._modality || entry.modality).toUpperCase());
      }

      mergeModalitySkillMaps(activeSkillsByModality, entry.activeSkillsByModality, isSkillActive);
      mergeModalitySkillMaps(explicitSkillsByModality, entry.explicitSkillsByModality, isSkillExplicitOne);

      if (Object.keys(activeSkillsByModality).length === 0) {
        const modalityList = Array.from(modalities);
        modalityList.forEach(mod => {
          Object.keys(skillValues).forEach(skill => {
            addSkillToModalityMap(activeSkillsByModality, mod, skill);
          });
        });
      }
      if (Object.keys(explicitSkillsByModality).length === 0) {
        const modalityList = Array.from(modalities);
        modalityList.forEach(mod => {
          Object.keys(explicitSkillValues).forEach(skill => {
            addSkillToModalityMap(explicitSkillsByModality, mod, skill);
          });
        });
      }

      const tasks = normalizeTasks(entry.tasks || entry.task);

      const last = merged[merged.length - 1];
      if (!last) {
        merged.push({
          start_time: entry.start_time,
          end_time: entry.end_time,
          TIME: entry.TIME,
          skillValues: { ...skillValues },
          explicitSkillValues: { ...explicitSkillValues },
          activeSkillsByModality: { ...activeSkillsByModality },
          explicitSkillsByModality: { ...explicitSkillsByModality },
          modalities,
          tasks: [...tasks]
        });
        return;
      }

      const lastEnd = timeToMinutes(last.end_time);
      if (start < lastEnd) {
        if (end > lastEnd) {
          last.end_time = entry.end_time;
        }
        last.TIME = `${last.start_time}-${last.end_time}`;
        Object.keys(skillValues).forEach(s => {
          last.skillValues[s] = 1;
        });
        Object.keys(explicitSkillValues).forEach(s => {
          last.explicitSkillValues[s] = 1;
        });
        mergeModalitySkillMaps(last.activeSkillsByModality, activeSkillsByModality, isSkillActive);
        mergeModalitySkillMaps(last.explicitSkillsByModality, explicitSkillsByModality, isSkillExplicitOne);
        modalities.forEach(m => last.modalities.add(m));
        tasks.forEach(task => last.tasks.push(task));
        last.tasks = Array.from(new Set(last.tasks));
        return;
      }

      merged.push({
        start_time: entry.start_time,
        end_time: entry.end_time,
        TIME: entry.TIME,
        skillValues: { ...skillValues },
        explicitSkillValues: { ...explicitSkillValues },
        activeSkillsByModality: { ...activeSkillsByModality },
        explicitSkillsByModality: { ...explicitSkillsByModality },
        modalities,
        tasks: [...tasks]
      });
    });

    return merged;
  }

  // Build time header row
  function buildTimeHeader(headerEl) {
    headerEl.innerHTML = '';
    for (let h = TIMELINE_START; h < TIMELINE_END; h++) {
      const slot = document.createElement('div');
      slot.className = 'time-slot';
      slot.textContent = `${h}:00`;
      headerEl.appendChild(slot);
    }
  }

  // Update current time indicator line
  function updateCurrentTimeLine(gridEl, lineId) {
    const existing = document.getElementById(lineId);
    if (existing) existing.remove();

    const now = new Date();
    const currentHour = now.getHours() + now.getMinutes() / 60;

    // Only show if within timeline bounds
    if (currentHour < TIMELINE_START || currentHour > TIMELINE_END) return;

    const percent = ((currentHour - TIMELINE_START) / TIMELINE_HOURS) * 100;

    const workerColWidth = getComputedStyle(document.documentElement).getPropertyValue('--worker-col-width') || '180px';
    const line = document.createElement('div');
    line.id = lineId;
    line.className = 'current-time-line';
    line.style.left = `calc(${workerColWidth.trim()} + (100% - ${workerColWidth.trim()}) * ${percent / 100})`;

    gridEl.appendChild(line);
  }

  /**
   * Render timeline chart
   * @param {Object} options Configuration options
   * @param {HTMLElement} options.gridEl - The timeline grid container element
   * @param {HTMLElement} options.headerEl - The time header element
   * @param {Array} options.data - Array of schedule entries
   * @param {Array} options.skillColumns - Array of skill column names
   * @param {Object} options.skillSlugMap - Map of skill names to slugs
   * @param {Object} options.skillColorMap - Map of skill slugs to colors
   * @param {boolean} options.mergeModalities - Whether to merge entries across modalities (ALL view)
   * @param {boolean} options.showCurrentTime - Whether to show current time indicator
   * @param {string} options.timeLineId - ID for the current time line element
   */
  function render(options) {
    const {
      gridEl,
      headerEl,
      data,
      skillColumns,
      skillSlugMap = {},
      skillColorMap = {},
      mergeModalities = true,
      showCurrentTime = true,
      timeLineId = 'current-time-line'
    } = options;

    if (!gridEl) {
      console.error('TimelineChart: gridEl is required');
      return;
    }

    // Clear existing content (keep header label if present)
    const headerLabel = gridEl.querySelector('.time-header-label');
    gridEl.innerHTML = '';

    // Re-add header label
    if (headerLabel) {
      gridEl.appendChild(headerLabel);
    } else {
      const label = document.createElement('div');
      label.className = 'time-header-label';
      label.textContent = 'Worker';
      gridEl.appendChild(label);
    }

    // Re-add time header
    if (headerEl) {
      gridEl.appendChild(headerEl);
      buildTimeHeader(headerEl);
    } else {
      const header = document.createElement('div');
      header.className = 'time-header';
      gridEl.appendChild(header);
      buildTimeHeader(header);
    }

    // Validate data
    if (!Array.isArray(data) || data.length === 0) {
      const empty = document.createElement('div');
      empty.className = 'empty-state';
      empty.textContent = 'No schedule data available';
      gridEl.appendChild(empty);
      return;
    }

    // Filter out invalid entries
    const validData = data.filter(e => {
      if (!e) return false;
      if (e.TIME === '00:00-00:00') return false;
      if (!e.start_time || !e.end_time) return false;
      return hasAnyVisibleSkill(e, skillColumns);
    }).map(entry => buildNormalizedTimelineEntry(entry, skillColumns));

    if (validData.length === 0) {
      const empty = document.createElement('div');
      empty.className = 'empty-state';
      empty.textContent = 'No active schedule entries';
      gridEl.appendChild(empty);
      return;
    }

    // Group entries by worker name
    const workerMap = new Map();
    validData.forEach(entry => {
      const worker = entry.PPL || entry.worker;
      if (!workerMap.has(worker)) {
        workerMap.set(worker, []);
      }
      workerMap.get(worker).push(entry);
    });

    // Sort workers by earliest start time, then role, then worker sort key
    const sortedWorkers = Array.from(workerMap.entries()).sort((a, b) => {
      const aStart = Math.min(...a[1].map(e => timeToMinutes(e.start_time)));
      const bStart = Math.min(...b[1].map(e => timeToMinutes(e.start_time)));
      if (aStart !== bStart) return aStart - bStart;

      const aTask = normalizeTasks(a[1][0]?.tasks || a[1][0]?.task)[0] || '';
      const bTask = normalizeTasks(b[1][0]?.tasks || b[1][0]?.task)[0] || '';
      const taskCmp = aTask.localeCompare(bTask);
      if (taskCmp !== 0) return taskCmp;

      return buildWorkerSortKey(a[0] || '').localeCompare(buildWorkerSortKey(b[0] || ''));
    });

    const isGapEntry = entry => {
      const rowType = (entry.row_type || '').toString().toLowerCase();
      return rowType === 'gap' || rowType === 'gap_segment';
    };

    // Create worker rows
    sortedWorkers.forEach(([worker, entries]) => {
      // Merge entries if in ALL view mode
      const gapEntries = entries.filter(isGapEntry);
      const shiftEntries = entries.filter(entry => !isGapEntry(entry));
      const processedEntries = mergeModalities ? mergeEntriesByTime(shiftEntries, skillColumns) : shiftEntries;
      const displayEntries = mergeEntriesForSingleLane(processedEntries, skillColumns);
      const combinedEntries = [...displayEntries, ...gapEntries].sort(
        (a, b) => timeToMinutes(a.start_time) - timeToMinutes(b.start_time)
      );

      // Collect all skills this worker has
      const workerSkills = new Set();
      combinedEntries.forEach(entry => {
        const skills = entry.skillValues
          ? Object.keys(entry.skillValues)
          : skillColumns.filter(s => isSkillActive(entry[s]));
        skills.forEach(s => {
          workerSkills.add(skillSlugMap[s] || s.toLowerCase());
        });
      });

      const row = document.createElement('div');
      row.className = 'worker-row';
      row.dataset.worker = worker;
      row.dataset.skills = Array.from(workerSkills).join(',');

      // Worker name cell
      const nameCell = document.createElement('div');
      nameCell.className = 'worker-name-cell';
      const workerLabel = window.WorkerNameUtils.formatDisplayName(worker);
      nameCell.textContent = workerLabel;

      // Timeline cell
      const timelineCell = document.createElement('div');
      timelineCell.className = 'worker-timeline';

      // Create shift bars
      combinedEntries.forEach(entry => {
        const left = timeToPercent(entry.start_time);
        const right = timeToPercent(entry.end_time);
        const width = right - left;

        if (width <= 0) return;

        if (isGapEntry(entry)) {
          const gapBar = document.createElement('div');
          gapBar.className = 'gap-bar';
          gapBar.style.left = `${left}%`;
          gapBar.style.width = `${width}%`;
          gapBar.style.zIndex = '2';

          const tasks = normalizeTasks(entry.tasks || entry.task);
          const activity = tasks.length ? tasks.join(', ') : 'Gap';
          gapBar.title = `${workerLabel}\n${activity}: ${entry.start_time}-${entry.end_time}`;

          timelineCell.appendChild(gapBar);
          return;
        }

        let activeSkills;

        if (entry.skillValues) {
          activeSkills = Object.keys(entry.skillValues)
            .map(s => skillSlugMap[s] || s.toLowerCase());
        } else {
          activeSkills = skillColumns
            .filter(s => isSkillActive(entry[s]))
            .map(s => skillSlugMap[s] || s.toLowerCase());
        }
        const displaySkills = activeSkills;
        const tooltipModSkillLabels = buildTooltipModSkillLabels(entry, skillColumns, skillSlugMap);

        const tasks = normalizeTasks(entry.tasks || entry.task);
        const taskTooltip = tasks.length ? `Shifts: ${tasks.join(', ')}\n` : '';

        if (displaySkills.length > 0) {
          const bar = document.createElement('div');
          bar.className = 'shift-bar';
          bar.style.left = `${left}%`;
          bar.style.width = `${width}%`;
          bar.style.background = buildSkillGradient(displaySkills, skillColorMap);
          bar.style.zIndex = '1';
          bar.dataset.skills = activeSkills.join(',');
          bar.dataset.hasActive = 'true';

          // Store modality data for filtering
          let modList = [];
          if (entry.modalities && entry.modalities.size > 0) {
            modList = Array.from(entry.modalities).map(m => m.toLowerCase());
          } else if (entry._modality || entry.modality) {
            modList = [(entry._modality || entry.modality).toLowerCase()];
          }
          bar.dataset.modalities = modList.join(',');

          // Tooltip
          const timeDisplay = entry.TIME || `${entry.start_time}-${entry.end_time}`;
          const skillsTooltip = `Active (${tooltipModSkillLabels.length}): ${tooltipModSkillLabels.join(', ') || 'none'}`;
          bar.title = `${workerLabel}\n${taskTooltip}Zeit: ${timeDisplay}\n${skillsTooltip}`;

          timelineCell.appendChild(bar);
        } else {
          const bar = document.createElement('div');
          bar.className = 'shift-bar shift-bar--neutral';
          bar.style.left = `${left}%`;
          bar.style.width = `${width}%`;
          bar.style.zIndex = '1';
          bar.dataset.skills = '';
          bar.dataset.hasActive = 'false';

          let modList = [];
          if (entry.modalities && entry.modalities.size > 0) {
            modList = Array.from(entry.modalities).map(m => m.toLowerCase());
          } else if (entry._modality || entry.modality) {
            modList = [(entry._modality || entry.modality).toLowerCase()];
          }
          bar.dataset.modalities = modList.join(',');

          const timeDisplay = entry.TIME || `${entry.start_time}-${entry.end_time}`;
          const skillsTooltip = 'Active (0): none';
          bar.title = `${workerLabel}\n${taskTooltip}Zeit: ${timeDisplay}\n${skillsTooltip}`;

          timelineCell.appendChild(bar);
        }

      });

      row.appendChild(nameCell);
      row.appendChild(timelineCell);
      gridEl.appendChild(row);
    });

    // Add current time indicator
    if (showCurrentTime) {
      updateCurrentTimeLine(gridEl, timeLineId);
    }
  }

  // Helper to show/hide row and its children (handles display:contents)
  function setRowVisibility(row, visible) {
    row.style.display = visible ? '' : 'none';
    // Also set children visibility for display:contents compatibility
    const nameCell = row.querySelector('.worker-name-cell');
    const timeline = row.querySelector('.worker-timeline');
    if (nameCell) nameCell.style.display = visible ? '' : 'none';
    if (timeline) timeline.style.display = visible ? '' : 'none';
  }

  // Filter rows by skill
  function filterBySkill(gridEl, skillSlug) {
    const rows = gridEl.querySelectorAll('.worker-row');
    rows.forEach(row => {
      const bars = Array.from(row.querySelectorAll('.shift-bar'));
      const gapBars = Array.from(row.querySelectorAll('.gap-bar'));

      // Show all bars when filter is cleared
      if (skillSlug === 'all' || !skillSlug) {
        bars.forEach(bar => bar.style.display = '');
        gapBars.forEach(bar => bar.style.display = '');
        setRowVisibility(row, true);
        return;
      }

      const matchingBars = bars.filter(bar => {
        const barSkills = (bar.dataset.skills || '').split(',').filter(s => s);
        return barSkills.includes(skillSlug);
      });

      // Show matching bars, hide the rest
      bars.forEach(bar => {
        const barSkills = (bar.dataset.skills || '').split(',').filter(s => s);
        bar.style.display = barSkills.includes(skillSlug) ? '' : 'none';
      });

      // Only show gaps when row has matching shift bars
      const hasMatchingShifts = matchingBars.length > 0;
      gapBars.forEach(bar => bar.style.display = hasMatchingShifts ? '' : 'none');

      // Hide row if no matching shift bars
      setRowVisibility(row, hasMatchingShifts);
    });
  }

  // Filter rows by modality
  function filterByModality(gridEl, modality) {
    const rows = gridEl.querySelectorAll('.worker-row');
    const mod = (modality || '').toLowerCase();

    rows.forEach(row => {
      const bars = Array.from(row.querySelectorAll('.shift-bar'));
      const gapBars = Array.from(row.querySelectorAll('.gap-bar'));

      // Show all bars when filter is cleared
      if (mod === 'all' || mod === '' || !mod) {
        bars.forEach(bar => bar.style.display = '');
        gapBars.forEach(bar => bar.style.display = '');
        setRowVisibility(row, true);
        return;
      }

      const matchingBars = bars.filter(bar => {
        const barMods = (bar.dataset.modalities || '').split(',').filter(m => m);
        return barMods.includes(mod);
      });

      // Show matching bars, hide the rest
      bars.forEach(bar => {
        const barMods = (bar.dataset.modalities || '').split(',').filter(m => m);
        bar.style.display = barMods.includes(mod) ? '' : 'none';
      });

      // Only show gaps when row has matching shift bars
      const hasMatchingShifts = matchingBars.length > 0;
      gapBars.forEach(bar => bar.style.display = hasMatchingShifts ? '' : 'none');

      // Hide row if no matching shift bars
      setRowVisibility(row, hasMatchingShifts);
    });
  }

  /**
   * Apply combined filters (skill, modality, hideZero) to timeline
   * When hideZero is true, only show workers who have active skills (1 or w)
   * for the filtered skill×modality combination.
   *
   * @param {HTMLElement} gridEl - The timeline grid element
   * @param {Object} filters - Filter options
   * @param {string} filters.skill - Skill slug to filter by (or 'all'/empty)
   * @param {string} filters.modality - Modality to filter by (or 'all'/empty)
   * @param {boolean} filters.hideZero - If true, hide rows without active skills for the filter combination
   */
  function applyFilters(gridEl, filters = {}) {
    const { skill = '', modality = '', hideZero = false } = filters;
    const rows = gridEl.querySelectorAll('.worker-row');
    const mod = (modality || '').toLowerCase();
    const skillSlug = (skill || '').toLowerCase();

    const hasModFilter = mod && mod !== 'all';
    const hasSkillFilter = skillSlug && skillSlug !== 'all';
    const anyFilterActive = hasModFilter || hasSkillFilter || hideZero;

    rows.forEach(row => {
      const bars = Array.from(row.querySelectorAll('.shift-bar'));
      const gapBars = Array.from(row.querySelectorAll('.gap-bar'));

      // No filters active - show everything
      if (!anyFilterActive) {
        bars.forEach(bar => bar.style.display = '');
        gapBars.forEach(bar => bar.style.display = '');
        setRowVisibility(row, true);
        return;
      }

      // Find bars that match the filter criteria
      const matchingBars = bars.filter(bar => {
        const barSkills = (bar.dataset.skills || '').split(',').filter(s => s);
        const barMods = (bar.dataset.modalities || '').split(',').filter(m => m);
        const hasActive = bar.dataset.hasActive !== 'false';
        const activeMatch = !hideZero || hasActive;

        // Check modality match (if filter set)
        const modMatch = !hasModFilter || barMods.includes(mod);
        // Check skill match (if filter set)
        const skillMatch = !hasSkillFilter || barSkills.includes(skillSlug);

        return modMatch && skillMatch && activeMatch;
      });

      const hasMatchingShifts = matchingBars.length > 0;
      if (hasMatchingShifts) {
        bars.forEach(bar => bar.style.display = '');
        gapBars.forEach(bar => bar.style.display = '');
        setRowVisibility(row, true);
      } else {
        bars.forEach(bar => bar.style.display = 'none');
        gapBars.forEach(bar => bar.style.display = 'none');
        setRowVisibility(row, false);
      }
    });
  }

  // Public API
  return {
    render,
    filterBySkill,
    filterByModality,
    applyFilters,
    updateCurrentTimeLine,
    timeToMinutes,
    timeToPercent,
    isSkillActive,
    isSkillVisible,
    hasAnyActiveSkill,
    hasAnyVisibleSkill,
    escapeHtml,
    TIMELINE_START,
    TIMELINE_END,
    TIMELINE_HOURS
  };
})();

// Export for module systems if available
if (typeof module !== 'undefined' && module.exports) {
  module.exports = TimelineChart;
}
