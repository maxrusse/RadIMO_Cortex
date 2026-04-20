// Helper: Render a skill select element with standard options
function renderSkillSelect(id, value, onchangeHandler, options = {}) {
  const val = normalizeSkillValueJS(value);
  const idAttr = id ? ` id="${id}"` : '';
  const changeStatements = [];
  if (onchangeHandler) changeStatements.push(onchangeHandler);
  changeStatements.push('syncSkillValueControlClass(this)');
  const changeAttr = ` onchange="${changeStatements.join('; ')}"`;
  const disabledAttr = options.disabled ? ' disabled' : '';
  const borderClass = getSkillBorderClass(val);
  return `<select${idAttr} class="skill-value-select ${borderClass}" data-skill-value="${displaySkillValue(val)}"${changeAttr}${disabledAttr}>
    <option value="-1" ${val === -1 ? 'selected' : ''}>-1</option>
    <option value="0" ${val === 0 ? 'selected' : ''}>0</option>
    <option value="1" ${val === 1 ? 'selected' : ''}>1</option>
    <option value="w" ${isWeightedSkill(val) ? 'selected' : ''}>w</option>
  </select>`;
}

function isVisibleSkillValue(value, filter) {
  if (filter?.hideZero) {
    return isActiveSkillValue(value);
  }
  return isNonNegativeSkillValue(value);
}

function groupHasActiveSkills(group, filter) {
  if (!group) return false;
  const shifts = getTableShifts(group).filter(s => !s.deleted);
  const nonGapShifts = shifts.filter(s => !s.is_gap_entry);
  if (nonGapShifts.length === 0) return false;

  const modalityFilter = filter.modality || '';
  const skillFilter = filter.skill || '';
  const modalitiesToCheck = modalityFilter ? [modalityFilter] : MODALITIES.map(m => m.toLowerCase());

  if (skillFilter) {
    return nonGapShifts.some(shift => modalitiesToCheck.some(modKey => {
      const modData = shift.modalities?.[modKey];
      if (!modData) return false;
      return isVisibleSkillValue(modData.skills?.[skillFilter], filter);
    }));
  }

  return nonGapShifts.some(shift => modalitiesToCheck.some(modKey => {
    const modData = shift.modalities?.[modKey];
    if (!modData) return false;
    return SKILLS.some(skill => isVisibleSkillValue(modData.skills?.[skill], filter));
  }));
}

function shiftMatchesFilters(shift, filter, group) {
  if (shift?.is_gap_entry) {
    if (!filter) return true;
    const filterActive = Boolean(filter.modality || filter.skill || filter.hideZero);
    return filterActive ? groupHasActiveSkills(group, filter) : true;
  }
  if (!filter) return true;
  const { modality, skill } = filter;
  const filterActive = Boolean(modality || skill || filter.hideZero);
  if (!filterActive) return true;

  const modalitiesToCheck = modality ? [modality] : MODALITIES.map(m => m.toLowerCase());
  let matchFound = false;

  for (const modKey of modalitiesToCheck) {
    const modData = shift.modalities[modKey];
    if (!modData) continue;

    if (skill) {
      const val = modData.skills[skill];
      if (isVisibleSkillValue(val, filter)) {
        matchFound = true;
        break;
      }
    } else {
      const hasSkill = SKILLS.some(s => {
        const val = modData.skills[s];
        return isVisibleSkillValue(val, filter);
      });
      if (hasSkill) {
        matchFound = true;
        break;
      }
    }
  }

  return matchFound;
}

function applyEditModeUI(tab) {
  // Update edit mode toggle button
  const btn = document.getElementById(`edit-mode-btn-${tab}`);
  if (btn) {
    btn.textContent = editMode[tab] ? 'Exit Edit Mode' : 'Quick Edit';
    btn.className = editMode[tab] ? 'btn btn-warning' : 'btn btn-secondary';
  }

  // Show/hide and update save button
  const saveBtn = document.getElementById(`save-inline-btn-${tab}`);
  if (saveBtn) {
    saveBtn.style.display = editMode[tab] ? 'inline-block' : 'none';
  }
  updateSaveButtonCount(tab);
  if (tab === 'tomorrow' && typeof updatePrepSelectionControls === 'function') {
    updatePrepSelectionControls();
  }

}

// Sort entries by column while keeping worker rows grouped
function sortEntries(tab, column) {
  const state = sortState[tab];
  if (state.column === column) {
    state.direction = state.direction === 'asc' ? 'desc' : 'asc';
  } else {
    state.column = column;
    state.direction = 'asc';
  }

  const entries = entriesData[tab];
  entries.sort((a, b) => {
    const aShift = getTableShifts(a)[0] || {};
    const bShift = getTableShifts(b)[0] || {};
    const aWorker = a.worker || '';
    const bWorker = b.worker || '';
    const aTime = aShift.start_time || '';
    const bTime = bShift.start_time || '';
    const aTask = aShift.task || '';
    const bTask = bShift.task || '';

    let cmp = 0;
    switch (column) {
      case 'worker':
        cmp = buildWorkerSortKey(aWorker).localeCompare(buildWorkerSortKey(bWorker))
          || aTime.localeCompare(bTime)
          || aTask.localeCompare(bTask);
        break;
      case 'task':
        cmp = aTask.localeCompare(bTask)
          || aTime.localeCompare(bTime)
          || buildWorkerSortKey(aWorker).localeCompare(buildWorkerSortKey(bWorker));
        break;
      case 'shift':
      default:
        cmp = aTime.localeCompare(bTime)
          || aTask.localeCompare(bTask)
          || buildWorkerSortKey(aWorker).localeCompare(buildWorkerSortKey(bWorker));
        break;
    }
    return state.direction === 'asc' ? cmp : -cmp;
  });

  renderTable(tab);
}

// Render table header - supports both modality-first and skill-first display orders
function renderTableHeader(tab) {
  const thead = document.getElementById(`table-head-${tab}`);
  if (!thead) return;
  const isEditMode = editMode[tab];
  const modalKeys = MODALITIES.map(m => m.toLowerCase());
  const sort = sortState[tab];

  const sortClass = (col) => `sortable ${sort.column === col ? (sort.direction === 'asc' ? 'sort-asc' : 'sort-desc') : ''}`;

  let headerHtml = '<tr class="header-top">';
  headerHtml += `<th rowspan="2" class="worker-col ${sortClass('worker')}" onclick="sortEntries('${tab}', 'worker')">Worker</th>`;
  headerHtml += `<th rowspan="2" class="shift-col ${sortClass('shift')}" onclick="sortEntries('${tab}', 'shift')">${isEditMode ? 'Time' : 'Time'}</th>`;
  headerHtml += `<th rowspan="2" class="task-col ${sortClass('task')}" onclick="sortEntries('${tab}', 'task')">Role</th>`;

  if (displayOrder === 'modality-first') {
    // Modalities as top-level columns (each spanning skill count)
    modalKeys.forEach(mod => {
      const modSettings = MODALITY_SETTINGS[mod] || {};
      const label = (modSettings.label || mod).toUpperCase();
      const navColor = modSettings.nav_color || '#6c757d';
      headerHtml += `<th colspan="${SKILLS.length}" class="skill-header" style="background:${navColor}; color:#fff;">${label}</th>`;
    });
  } else {
    // Skills as top-level columns (each spanning modality count)
    SKILLS.forEach(skill => {
      const skillSettings = SKILL_SETTINGS[skill] || {};
      const btnColor = skillSettings.button_color || '#6c757d';
      const textColor = skillSettings.text_color || '#ffffff';
      headerHtml += `<th colspan="${modalKeys.length}" class="skill-header" style="background:${btnColor}; color:${textColor};">${escapeHtml(skill)}</th>`;
    });
  }

  headerHtml += '<th rowspan="2" class="modifier-col">Load Mod.</th>';
  headerHtml += '<th rowspan="2">Actions</th>';
  headerHtml += '</tr>';

  // Second header row: sub-columns (3-char labels for compactness)
  headerHtml += '<tr class="header-sub">';
  if (displayOrder === 'modality-first') {
    // Skill labels under each modality
    modalKeys.forEach(() => {
      SKILLS.forEach(skill => {
        const shortLabel = skill.substring(0, 3);
        headerHtml += `<th class="sub-col" title="${escapeHtml(skill)}">${shortLabel}</th>`;
      });
    });
  } else {
    // Modality labels under each skill
    SKILLS.forEach(() => {
      modalKeys.forEach(mod => {
        const modSettings = MODALITY_SETTINGS[mod] || {};
        const label = (modSettings.label || mod).replace(/-/g, '');
        const shortLabel = label.substring(0, 3).toUpperCase();
        headerHtml += `<th class="sub-col" title="${escapeHtml(label)}">${shortLabel}</th>`;
      });
    });
  }

  headerHtml += '</tr>';

  thead.innerHTML = headerHtml;
}

// Render grouped table by worker - one row per modality entry with skill columns
// Shows ALL modalities for each shift (even those with -1)
function renderSummary(tab, groups) {
  const summaryEl = document.getElementById(`summary-${tab}`);
  if (!summaryEl) return;

  const counts = {};
  SKILLS.forEach(skill => {
    counts[skill] = {};
    MODALITIES.forEach(mod => counts[skill][mod.toLowerCase()] = 0);
  });

  groups.forEach(group => {
    const shifts = getTableShifts(group);
    SKILLS.forEach(skill => {
      MODALITIES.forEach(mod => {
        const modKey = mod.toLowerCase();
        const hasActive = shifts.some(shift => {
          const modData = shift.modalities[modKey];
          if (!modData) return false;
          const val = modData.skills[skill];
          return isActiveSkillValue(val);
        });
        if (hasActive) {
          counts[skill][modKey] += 1;
        }
      });
    });
  });

  let html;
  if (displayOrder === 'modality-first') {
    html = '<div class="summary-title">Active counts by modality & skill (w and 1 counted once per worker)</div>';
    html += '<table class="summary-table"><thead><tr><th>Modality</th>';
    SKILLS.forEach(skill => {
      html += `<th>${escapeHtml(skill)}</th>`;
    });
    html += '</tr></thead><tbody>';

    MODALITIES.forEach(mod => {
      const modSettings = MODALITY_SETTINGS[mod.toLowerCase()] || {};
      const navColor = modSettings.nav_color || '#6c757d';
      html += `<tr><td style="text-align:left; font-weight:600; background:${navColor}20;">${mod.toUpperCase()}</td>`;
      SKILLS.forEach(skill => {
        html += `<td>${counts[skill][mod.toLowerCase()]}</td>`;
      });
      html += '</tr>';
    });
  } else {
    html = '<div class="summary-title">Active counts by skill & modality (w and 1 counted once per worker)</div>';
    html += '<table class="summary-table"><thead><tr><th>Skill</th>';
    MODALITIES.forEach(mod => {
      html += `<th>${mod.toUpperCase()}</th>`;
    });
    html += '</tr></thead><tbody>';

    SKILLS.forEach(skill => {
      const skillSettings = SKILL_SETTINGS[skill] || {};
      const btnColor = skillSettings.button_color || '#6c757d';
      html += `<tr><td style="text-align:left; font-weight:600; background:${btnColor}20;">${escapeHtml(skill)}</td>`;
      MODALITIES.forEach(mod => {
        html += `<td>${counts[skill][mod.toLowerCase()]}</td>`;
      });
      html += '</tr>';
    });
  }

  html += '</tbody></table>';
  summaryEl.innerHTML = html;
}

function renderTable(tab) {
  // First update the header
  renderTableHeader(tab);

  const tbody = document.getElementById(`table-body-${tab}`);
  if (!tbody) return;
  tbody.innerHTML = '';

  const groups = entriesData[tab];
  const isEditMode = editMode[tab];
  const filter = tableFilters[tab] || {};
  const filterActive = Boolean(filter.modality || filter.skill || filter.hideZero);
  const filterHighlightActive = Boolean(filter.modality || filter.skill);
  const visibleGroups = [];

  const modCount = MODALITIES.length;
  // Calculate column count: Worker + Shift + Task + (Skills × Modalities) + 1 Modifier + Actions
  const colCount = 3 + (SKILLS.length * modCount) + 1 + 1;

  if (!groups || groups.length === 0) {
    tbody.innerHTML = `<tr><td colspan="${colCount}" style="text-align: center; padding: 2rem; color: #666;">No data. Load from CSV first.</td></tr>`;
    renderSummary(tab, []);
    return;
  }

  groups.forEach((group, gIdx) => {
    const shifts = getTableShifts(group).filter(shift => !shift.deleted);
    if (shifts.length === 0) return;

    if (filterActive && !groupHasActiveSkills(group, filter)) {
      return;
    }

    const shiftsToRender = shifts;

    const workerLabel = getWorkerDisplayName(group.worker);
    const escapedWorker = escapeHtml(workerLabel);

    const totalRows = shiftsToRender.length;
    const isDuplicate = shifts.length > 1;
    const duplicateBadge = isDuplicate ? `<span class="duplicate-badge">${shifts.length} shifts</span>` : '';
    const hasNonGapShift = shifts.some(shift => !shift.is_gap_entry);
    const hasGapRows = (group.allGaps || []).length > 0;
    const warningMessages = [];
    if (!hasNonGapShift && hasGapRows) {
      warningMessages.push('Gaps only (no shifts)');
    }
    const warningTitle = warningMessages.length
      ? ` title="${escapeHtml(warningMessages.join(' | '))}"`
      : '';

    shiftsToRender.forEach((shift, shiftIdx) => {
      const tr = document.createElement('tr');
      const modKeysToShow = MODALITIES.map(m => m.toLowerCase());
      const quickBreakDisabled = tab === 'today' && editMode[tab];

      if (shift.is_manual) {
        tr.classList.add('row-manual');
      }

      if (shiftIdx === 0) {
        tr.classList.add('worker-group-first');
        let workerHtml = `<span class="worker-name ${isDuplicate ? 'duplicate' : ''}"${warningTitle}>${escapedWorker}</span>${duplicateBadge}`;
        // Add quick break button at worker level (today tab only)
        if (tab === 'today') {
          workerHtml += `<button type="button" class="btn-quick-gap" onclick="onQuickGap30('${tab}', ${gIdx})" title="${quickBreakDisabled ? 'Exit Quick Edit before adding a break' : `Add ${QUICK_BREAK.duration_minutes}-min break NOW`}" ${quickBreakDisabled ? 'disabled' : ''}>☕</button>`;
        }
        tr.innerHTML += `<td rowspan="${totalRows}" style="vertical-align: middle;">${workerHtml}</td>`;
      }

      // is_gap_entry is set from row_type in buildEntriesByWorker
      const isGapRow = Boolean(shift.is_gap_entry);
      // Build timeline display
      const segments = shift.timeSegments || [{ start: shift.start_time, end: shift.end_time }];

      if (isEditMode) {
        // In edit mode, show editable times with gap info below
        const firstSeg = segments[0] || {};
        const lastSeg = segments[segments.length - 1] || firstSeg;
        let shiftEditor = `<div style="display:flex; gap:0.2rem; align-items:center; font-size:0.7rem;">
            <input type="time" value="${firstSeg.start || '07:00'}" onchange="onInlineTimeChange('${tab}', ${gIdx}, ${shiftIdx}, 'start', this.value)" style="padding: 0.1rem; font-size: 0.7rem; width: 65px;">
            -
            <input type="time" value="${lastSeg.end || '15:00'}" onchange="onInlineTimeChange('${tab}', ${gIdx}, ${shiftIdx}, 'end', this.value)" style="padding: 0.1rem; font-size: 0.7rem; width: 65px;">
            <button type="button" class="btn-inline-delete" onclick="deleteShiftInline('${tab}', ${gIdx}, ${shiftIdx})" title="Delete this shift">×</button>
          </div>`;
        tr.innerHTML += `<td class="grid-cell shift-col">${shiftEditor}</td>`;
      } else {
        // View mode: show timeline with segments and gaps in time order
        let timelineHtml = '<div class="shift-timeline">';

        if (isGapRow) {
          const firstSeg = segments[0] || {};
          const lastSeg = segments[segments.length - 1] || firstSeg;
          timelineHtml += `<span class="gap-indicator">${escapeHtml(firstSeg.start || shift.start_time || '12:00')}-${escapeHtml(lastSeg.end || shift.end_time || '13:00')}</span>`;
        } else {
          segments.forEach(seg => {
            timelineHtml += `<span class="shift-segment">${escapeHtml(seg.start)}-${escapeHtml(seg.end)}</span>`;
          });
        }

        timelineHtml += '</div>';
        tr.innerHTML += `<td class="grid-cell shift-col">${timelineHtml}</td>`;
      }

      const taskStr = shift.task || '';
      const taskBadgeClass = isGapRow ? 'task-badge exclusion' : 'task-badge';
      tr.innerHTML += `<td class="grid-cell task-col">${taskStr ? `<span class="${taskBadgeClass}">${escapeHtml(taskStr)}</span>` : '<span style="color:#aaa;">-</span>'}</td>`;

      // Render data cells based on display order
      const renderCell = (modKey, skill) => {
        const modData = shift.modalities[modKey] || { skills: {}, row_index: -1, modifier: 1.0 };
        const isAssigned = modData.row_index !== undefined && modData.row_index >= 0;
        // Only mark as gap if this entry is truly a gap segment row
        const isGap = isGapRow;
        const rawVal = modData.skills[skill] !== undefined ? modData.skills[skill] : -1;
        const val = normalizeSkillValueJS(rawVal);

        // Background color based on display mode:
        // - modality-first: use modality background color
        // - skill-first: use skill background color (from button_color)
        let cellBg = '#fafafa';
        if (isAssigned && (val === 1 || isWeightedSkill(val))) {
          if (displayOrder === 'modality-first') {
            const modSettings = MODALITY_SETTINGS[modKey] || {};
            cellBg = modSettings.background_color || '#fff';
          } else {
            const skillSettings = SKILL_SETTINGS[skill] || {};
            const skillBtnColor = skillSettings.button_color || '#6c757d';
            cellBg = skillBtnColor + '15';  // 15% opacity for subtle background
          }
        }
        let isFilteredMatch = false;
        if (filterHighlightActive) {
          const matchesModality = !filter.modality || filter.modality === modKey;
          const matchesSkill = !filter.skill || filter.skill === skill;
          if (matchesModality && matchesSkill) {
            const filterVal = modData.skills[skill];
            isFilteredMatch = isVisibleSkillValue(filterVal, filter);
          }
        }
        const cellClass = `grid-cell ${isAssigned ? '' : 'ghost'}${isFilteredMatch ? ' filtered-cell' : ''}`;

        const displayVal = displaySkillValue(val);
        const skillClass = getSkillClass(val);
        const borderClass = getSkillBorderClass(val);
        if (isEditMode) {
          return `<td class="${cellClass}" style="background:${cellBg};">
            <input type="text" class="grid-input skill-value-input ${borderClass}" value="${displayVal}"
              data-tab="${tab}" data-mod="${modKey}" data-row="${modData.row_index}"
              data-skill="${skill}" data-gidx="${gIdx}" data-sidx="${shiftIdx}"
              data-skill-value="${displayVal}"
              onblur="validateAndSaveSkill(this)" onkeydown="handleSkillKeydown(event, this)">
          </td>`;
        } else {
          return `<td class="${cellClass}" style="background:${cellBg};"><span class="grid-badge skill-val ${skillClass}">${displayVal}</span></td>`;
        }
      };

      if (displayOrder === 'modality-first') {
        modKeysToShow.forEach(modKey => {
          SKILLS.forEach(skill => {
            tr.innerHTML += renderCell(modKey, skill);
          });
        });
      } else {
        SKILLS.forEach(skill => {
          modKeysToShow.forEach(modKey => {
            tr.innerHTML += renderCell(modKey, skill);
          });
        });
      }

      // Single modifier column for entire shift (applies to all modalities)
      const hasAnyAssigned = modKeysToShow.some(modKey => {
        const modData = shift.modalities[modKey];
        return modData && modData.row_index !== undefined && modData.row_index >= 0;
      });
      const modVal = shift.modifier || 1.0;
      const modCellClass = `grid-cell grid-modifier ${hasAnyAssigned ? '' : 'ghost'}`;
      const modClass = modVal > 1 ? 'modifier-high' : (modVal < 1 ? 'modifier-low' : '');
      if (isEditMode) {
        tr.innerHTML += `<td class="${modCellClass}">
          <input type="text" class="grid-mod-input" value="${modVal}"
            data-tab="${tab}" data-gidx="${gIdx}" data-sidx="${shiftIdx}"
            onblur="validateAndSaveShiftModifier(this)" onkeydown="handleModKeydown(event, this)">
        </td>`;
      } else {
        tr.innerHTML += `<td class="${modCellClass}"><span class="modifier-badge ${modClass}">${modVal.toFixed(2)}x</span></td>`;
      }

      if (shiftIdx === 0) {
        // Hide Edit/Del buttons in quick edit mode to avoid confusion
        if (isEditMode) {
          tr.innerHTML += `<td rowspan="${totalRows}" class="action-cell" style="vertical-align: middle; color: #999; font-size: 0.7rem;">
            <em>Save to edit</em>
          </td>`;
        } else {
          tr.innerHTML += `
            <td rowspan="${totalRows}" class="action-cell" style="vertical-align: middle;">
              <button class="btn btn-small btn-primary" onclick="openEditModal('${tab}', ${gIdx})" title="Edit">Edit</button>
              <button class="btn btn-small btn-danger" onclick="deleteWorkerEntries('${tab}', ${gIdx})" title="Delete All">Del</button>
            </td>`;
        }
      }

      tbody.appendChild(tr);
    });

    visibleGroups.push({ ...group, shiftsArray: shiftsToRender });
  });

  if (filterActive && tbody.children.length === 0) {
    tbody.innerHTML = `<tr><td colspan="${colCount}" style="text-align: center; padding: 1.25rem; color: #666;">No rows match the current filters.</td></tr>`;
  }

  if (!filterActive) {
    renderSummary(tab, groups);
  } else {
    renderSummary(tab, visibleGroups);
  }
}

function renderEditModalContent() {
  const { tab, groupIdx } = currentEditEntry;
  const group = entriesData[tab][groupIdx];
  if (!group) return;
  setEditPlanDraftFromGroup(group);
  const isEditable = true;

  let html = '';

  // XSS-safe rendering
  const workerLabel = getWorkerDisplayName(group.worker);
  const escapedWorker = escapeHtml(workerLabel);
  const shifts = getModalShifts(group);
  const numShifts = shifts.length;
  const duplicateBadge = numShifts > 1 ? `<span class="duplicate-badge">${numShifts}x</span>` : '';
  const borderColor = tab === 'today' ? (UI_COLORS.today_tab || '#28a745') : (UI_COLORS.tomorrow_tab || '#ffc107');

  // Header with worker name
  html += `<div style="margin-bottom: 1rem; padding: 0.75rem; background: #f8f9fa; border-radius: 8px;">
    <div class="form-group" style="margin-bottom: 0;">
      <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.3rem;">
        <label style="font-weight: 600;">Worker</label>
      </div>
      <div style="font-size: 1rem; padding: 0.5rem; background: #e9ecef; border-radius: 4px;">
        <strong>${escapedWorker}</strong> ${duplicateBadge}
      </div>
      <div style="margin-top: 0.4rem; font-size: 0.75rem; color: #666;">
        Changes are saved only when you click <strong>Save Edits</strong>.
      </div>
    </div>
  </div>`;

  // Section title for existing shifts
  html += `<div style="margin-bottom: 0.5rem; display: flex; justify-content: space-between; align-items: center;">
    <label style="font-weight: 600; font-size: 1rem;">Existing Shifts/Tasks</label>
  </div>`;


  // Render each existing shift section (like Add Worker task cards)
  shifts.forEach((shift, shiftIdx) => {
    // Assigned modalities (row_index >= 0)
    const assignedMods = Object.entries(shift.modalities)
      .filter(([_, data]) => data.row_index !== undefined && data.row_index >= 0)
      .map(([mod]) => mod);

    const primaryMod = assignedMods[0] || MODALITIES[0]?.toLowerCase() || 'ct';
    const modData = shift.modalities[primaryMod] || { skills: {}, row_index: -1, modifier: shift.modifier || 1.0 };

    // is_gap_entry is set from row_type in buildEntriesByWorker
    const isGapEntry = Boolean(shift.is_gap_entry);

    // Build timeline for the row (gaps are separate rows)
    const segments = shift.timeSegments || [{ start: shift.start_time, end: shift.end_time }];

    let timelineHtml = '<div class="shift-timeline">';
    if (isGapEntry) {
      const firstSeg = segments[0] || {};
      const lastSeg = segments[segments.length - 1] || firstSeg;
      timelineHtml += `<span class="gap-indicator">${escapeHtml(firstSeg.start || shift.start_time || '12:00')}-${escapeHtml(lastSeg.end || shift.end_time || '13:00')}</span>`;
    } else {
      segments.forEach(seg => {
        timelineHtml += `<span class="shift-segment">${escapeHtml(seg.start)}-${escapeHtml(seg.end)}</span>`;
      });
    }
    timelineHtml += '</div>';

    html += `<div style="margin-bottom: 1rem; padding: 0.75rem; border: 2px solid ${borderColor}; border-radius: 8px; background: #fafafa;">
<div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.5rem;">
  <span style="font-weight: 600; color: #333;">Shift ${shiftIdx + 1}${isGapEntry ? ' <span style="background:#f8d7da;color:#721c24;padding:0.1rem 0.3rem;border-radius:3px;font-size:0.7rem;">GAP</span>' : ''}</span>
  <div style="display:flex; gap:0.35rem; align-items:center;">
    ${isEditable ? `<button class="btn btn-small" style="background: #dc3545; color: white;" onclick="deleteShiftFromModal(${shiftIdx})">✕ Delete</button>` : ''}
  </div>
</div>

<div style="display: flex; gap: 0.5rem; flex-wrap: wrap; align-items: flex-end; margin-bottom: 0.5rem;">
  <div style="flex: 1; min-width: 180px;">
    <label style="font-size: 0.75rem; color: #666; display: block;">Shift / Task</label>
    <select id="edit-shift-${shiftIdx}-task" onchange="onEditShiftTaskChange(${shiftIdx}, this.value)" style="width: 100%; padding: 0.4rem; font-size: 0.85rem;" ${isEditable ? '' : 'disabled'}>
      ${renderTaskOptionsWithGroups(shift.task || '', true)}
    </select>
  </div>

  <div style="min-width: 90px;">
    <label style="font-size: 0.75rem; color: #666; display: block;">Start</label>
    <input type="time" id="edit-shift-${shiftIdx}-start" value="${shift.start_time || '07:00'}" style="padding: 0.4rem; font-size: 0.85rem;"
      onblur="commitModalTimeEdit(${shiftIdx}, 'start_time', this)" onkeydown="commitModalTimeOnEnter(event, ${shiftIdx}, 'start_time', this)" ${isEditable ? '' : 'disabled'}>
  </div>

  <div style="min-width: 90px;">
    <label style="font-size: 0.75rem; color: #666; display: block;">End</label>
    <input type="time" id="edit-shift-${shiftIdx}-end" value="${shift.end_time || '15:00'}" style="padding: 0.4rem; font-size: 0.85rem;"
      onblur="commitModalTimeEdit(${shiftIdx}, 'end_time', this)" onkeydown="commitModalTimeOnEnter(event, ${shiftIdx}, 'end_time', this)" ${isEditable ? '' : 'disabled'}>
  </div>

  <div style="min-width: 70px;">
    <label style="font-size: 0.75rem; color: #666; display: block;">Shift Load Modifier</label>
    <select id="edit-shift-${shiftIdx}-modifier" style="padding: 0.4rem; font-size: 0.85rem;"
      onchange="updateShiftFromModal(${shiftIdx}, { Modifier: parseFloat(this.value) })" ${isEditable ? '' : 'disabled'}>
      <option value="0.3" ${shift.modifier === 0.3 ? 'selected' : ''}>0.3x (~30% load)</option>
      <option value="0.5" ${shift.modifier === 0.5 ? 'selected' : ''}>0.5x</option>
      <option value="0.75" ${shift.modifier === 0.75 ? 'selected' : ''}>0.75x</option>
      <option value="0.9" ${shift.modifier === 0.9 ? 'selected' : ''}>0.9x</option>
      <option value="1.0" ${!shift.modifier || shift.modifier === 1.0 ? 'selected' : ''}>1.0x</option>
      <option value="1.1" ${shift.modifier === 1.1 ? 'selected' : ''}>1.1x</option>
      <option value="1.2" ${shift.modifier === 1.2 ? 'selected' : ''}>1.2x</option>
      <option value="1.25" ${shift.modifier === 1.25 ? 'selected' : ''}>1.25x</option>
    </select>
  </div>

  <div style="min-width: 100px;">
    <label style="font-size: 0.75rem; color: #666; display: block;">Hrs Count</label>
    <label class="hours-toggle" title="Checked = hours count towards load balancing. Unchecked = hours do NOT count.">
      <input type="checkbox" id="edit-shift-${shiftIdx}-counts-hours" ${shift.counts_for_hours !== false ? 'checked' : ''} onchange="updateHoursToggleLabel(this); updateShiftFromModal(${shiftIdx}, { counts_for_hours: this.checked })" ${isEditable ? '' : 'disabled'}>
      <span class="hours-toggle-label ${shift.counts_for_hours !== false ? 'counts' : 'no-count'}">${shift.counts_for_hours !== false ? 'Counts' : 'No count'}</span>
    </label>
  </div>

  <div style="min-width: 115px;">
    <label style="font-size: 0.75rem; color: #666; display: block;">Training</label>
    <label class="hours-toggle" title="Checked = weighted skills stay as configured. Unchecked = weighted skills on this row become -1.">
      <input type="checkbox" id="edit-shift-${shiftIdx}-training" ${shift.training !== false ? 'checked' : ''} onchange="onEditShiftTrainingChange(${shiftIdx}, this.checked)" ${isEditable && !isGapEntry ? '' : 'disabled'}>
      <span class="hours-toggle-label ${shift.training !== false ? 'counts' : 'no-count'}" data-role="training-label">${shift.training !== false ? 'Training on' : 'Training off'}</span>
    </label>
  </div>

  <div style="flex: 1; min-width: 240px;">
    <label style="font-size: 0.75rem; color: #666; display: block;">Timeline</label>
    ${timelineHtml}
  </div>
</div>

<div style="margin-bottom:0.35rem; display:flex; justify-content: space-between; align-items:center;">
  <label style="font-size:0.8rem; font-weight:600;">Skills per modality</label>
</div>

<table class="worker-skill-table">
  <thead>
    <tr>
      <th class="modality-header">Modality</th>`;

    // Skill column headers
    SKILLS.forEach(skill => {
      const skillSettings = SKILL_SETTINGS[skill] || {};
      const btnColor = skillSettings.button_color || '#6c757d';
      const textColor = skillSettings.text_color || '#fff';
      html += `<th><span class="skill-header" style="background:${btnColor}; color:${textColor};">${escapeHtml(skill)}</span></th>`;
    });

    html += `</tr>
  </thead>
  <tbody>`;

    // One row per modality
    MODALITIES.forEach(mod => {
      const modKey = mod.toLowerCase();
      const data = shift.modalities[modKey] || { skills: {}, row_index: -1, modifier: shift.modifier || 1.0 };
      const navColor = getModalityColor(modKey);
      const rowIndex = data.row_index !== undefined ? data.row_index : -1;

      html += `<tr>
      <td class="modality-header" style="color:${navColor}; font-weight:600;">${mod.toUpperCase()}
        <input type="hidden" id="edit-shift-${shiftIdx}-${modKey}-rowindex" value="${rowIndex}">
      </td>`;

      SKILLS.forEach(skill => {
        const val = data.skills[skill] !== undefined ? data.skills[skill] : (isGapEntry ? -1 : 0);
        const selectId = `edit-shift-${shiftIdx}-${modKey}-skill-${skill}`;
        const onchangeHandler = `updateShiftSkillFromModal(${shiftIdx}, '${modKey}', '${skill}', this.value)`;
        html += `<td>${renderSkillSelect(selectId, val, onchangeHandler, { disabled: !isEditable })}</td>`;
      });

      html += `</tr>`;
    });

    html += `</tbody>
</table>
  </div>`;
  });



  // Add New Shift/Gap section (same styling as Add Worker modal)
  if (isEditable) {
    html += `<div style="margin-bottom: 1rem; padding: 0.75rem; background: #d4edda; border: 2px solid #28a745; border-radius: 8px;">
  <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.5rem;">
<label style="font-weight: 600; color: #155724;">+ Add New Shift / Gap</label>
<div style="display: flex; gap: 0.5rem;">
  <button class="btn btn-small btn-success" type="button" onclick="addShiftFromModal()">Add</button>
</div>
  </div>
  <div style="display: flex; gap: 0.5rem; flex-wrap: wrap; align-items: flex-end; margin-bottom: 0.5rem;">
<div style="flex: 1; min-width: 180px;">
  <label style="font-size: 0.75rem; color: #666; display: block;">Shift / Task</label>
  <select id="modal-add-task" onchange="onModalTaskChange()" style="width: 100%; padding: 0.4rem; font-size: 0.85rem;">
    ${renderTaskOptionsWithGroups('', true, true)}
  </select>
</div>
<div style="min-width: 90px;">
  <label style="font-size: 0.75rem; color: #666; display: block;">Start</label>
  <input type="time" id="modal-add-start" value="07:00" style="padding: 0.4rem; font-size: 0.85rem;">
</div>
<div style="min-width: 90px;">
  <label style="font-size: 0.75rem; color: #666; display: block;">End</label>
  <input type="time" id="modal-add-end" value="15:00" style="padding: 0.4rem; font-size: 0.85rem;">
</div>
<div style="min-width: 70px;">
  <label style="font-size: 0.75rem; color: #666; display: block;">Shift Load Modifier</label>
  <select id="modal-add-modifier" style="padding: 0.4rem; font-size: 0.85rem;">
    <option value="0.3">0.3x (~30% load)</option>
    <option value="0.5">0.5x</option>
    <option value="0.75">0.75x</option>
    <option value="0.9">0.9x</option>
    <option value="1.0" selected>1.0x</option>
    <option value="1.1">1.1x</option>
    <option value="1.2">1.2x</option>
    <option value="1.25">1.25x</option>
  </select>
</div>
<div style="min-width: 100px;">
  <label style="font-size: 0.75rem; color: #666; display: block;">Hrs Count</label>
  <label class="hours-toggle" title="Checked = hours count towards load balancing. Unchecked = hours do NOT count.">
    <input type="checkbox" id="modal-add-counts-hours" checked onchange="updateHoursToggleLabel(this)">
    <span class="hours-toggle-label counts">Counts</span>
  </label>
</div>
<div style="min-width: 115px;">
  <label style="font-size: 0.75rem; color: #666; display: block;">Training</label>
  <label class="hours-toggle" title="Checked = weighted skills stay as configured. Unchecked = weighted skills on this added shift become -1.">
    <input type="checkbox" id="modal-add-training" checked onchange="onModalAddTrainingChange(this.checked); updateTrainingToggleLabel(this)">
    <span class="hours-toggle-label counts" data-role="training-label">Training on</span>
  </label>
</div>
  </div>
  <div style="margin-bottom:0.35rem; display:flex; justify-content: space-between; align-items:center;">
<label style="font-size:0.8rem; font-weight:600;">Skills per modality</label>
<span style="font-size:0.75rem; color:#555;">All modalities shown - set skill values per row</span>
  </div>
  <table class="worker-skill-table" id="modal-add-skill-table">
    <thead>
      <tr>
        <th class="modality-header">Modality</th>`;
  SKILLS.forEach(skill => {
    const skillSettings = SKILL_SETTINGS[skill] || {};
    const btnColor = skillSettings.button_color || '#6c757d';
    const textColor = skillSettings.text_color || '#fff';
    html += `<th><span class="skill-header" style="background:${btnColor}; color:${textColor};">${escapeHtml(skill)}</span></th>`;
  });
  html += `</tr>
    </thead>
    <tbody>`;
  MODALITIES.forEach(mod => {
    const modKey = mod.toLowerCase();
    const navColor = getModalityColor(modKey);
    html += `<tr>
      <td class="modality-header" style="color:${navColor}; font-weight:600;">${mod.toUpperCase()}</td>`;
    SKILLS.forEach(skill => {
      const selectId = `modal-add-${modKey}-skill-${skill}`;
      html += `<td>${renderSkillSelect(selectId, 0, 'onModalAddSkillChange(this)')}</td>`;
    });
    html += `</tr>`;
  });
  html += `</tbody>
  </table>
</div>`;
  }

  document.getElementById('modal-title').textContent = `Edit Worker - ${getWorkerDisplayName(group.worker)}`;
  document.getElementById('modal-content').innerHTML = html;
  applyModalEditModeUI();

  // Prefill the add-shift section with config + roster defaults for faster entry
  if (isEditable) {
    initializeModalAddForm();
  }
}

function renderAddWorkerModalContent(containerId = addWorkerModalState.containerId || 'modal-content') {
  const container = document.getElementById(containerId);
  if (!container) return;
  const workerInput = document.getElementById('add-worker-name-input');
  const currentWorkerName = workerInput ? workerInput.value : '';

  let html = '';

  // Worker name input
  html += `<div style="margin-bottom: 1rem; padding: 0.75rem; background: #f8f9fa; border-radius: 8px;">
    <div class="form-group" style="margin-bottom: 0;">
      <label style="font-weight: 600; display: block; margin-bottom: 0.3rem;">Worker Name</label>
      <input type="text" id="add-worker-name-input" value="${escapeHtml(currentWorkerName)}" placeholder="e.g. Müller, Anna (AM)"
             list="worker-list-datalist" autocomplete="off" onchange="onAddWorkerNameChange()"
             style="width: 100%; max-width: 300px; padding: 0.5rem; font-size: 1rem; border: 1px solid #ccc; border-radius: 4px;">
      <div style="margin-top: 0.4rem; font-size: 0.75rem; color: #666;">
        Bitte Medweb-Schreibweise bzw. Medweb-ID verwenden, sonst kann ein separater Worker-Eintrag entstehen.
      </div>
    </div>
  </div>`;

  // Tasks section
  html += `<div style="margin-bottom: 0.5rem; display: flex; justify-content: space-between; align-items: center;">
    <label style="font-weight: 600; font-size: 1rem;">Tasks/Shifts</label>
    <button class="btn btn-success btn-small" onclick="addTaskToAddWorkerModal(); renderAddWorkerModalContent();">+ Add Task</button>
  </div>`;

  // Render each task
  addWorkerModalState.tasks.forEach((task, idx) => {
    const borderColor = addWorkerModalState.tab === 'today' ? (UI_COLORS.today_tab || '#28a745') : (UI_COLORS.tomorrow_tab || '#ffc107');

    html += `<div style="margin-bottom: 1rem; padding: 0.75rem; border: 2px solid ${borderColor}; border-radius: 8px; background: #fafafa;">
      <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.5rem;">
        <span style="font-weight: 600; color: #333;">Task ${idx + 1}</span>
        <button class="btn btn-small" style="background: #dc3545; color: white;" onclick="removeTaskFromAddWorkerModal(${idx})">✕ Remove</button>
      </div>

      <div style="display: flex; gap: 0.5rem; flex-wrap: wrap; align-items: flex-end; margin-bottom: 0.5rem;">
        <div style="flex: 1; min-width: 180px;">
          <label style="font-size: 0.75rem; color: #666; display: block;">Shift / Task</label>
          <select onchange="updateAddWorkerTask(${idx}, 'task', this.value)" style="width: 100%; padding: 0.4rem; font-size: 0.85rem;">
            ${renderTaskOptionsWithGroups(task.task, true)}
          </select>
        </div>

        <div style="min-width: 90px;">
          <label style="font-size: 0.75rem; color: #666; display: block;">Start</label>
          <input type="time" value="${task.start_time}" onchange="updateAddWorkerTask(${idx}, 'start_time', this.value)" style="padding: 0.4rem; font-size: 0.85rem;">
        </div>

        <div style="min-width: 90px;">
          <label style="font-size: 0.75rem; color: #666; display: block;">End</label>
          <input type="time" value="${task.end_time}" onchange="updateAddWorkerTask(${idx}, 'end_time', this.value)" style="padding: 0.4rem; font-size: 0.85rem;">
        </div>

        <div style="min-width: 70px;">
          <label style="font-size: 0.75rem; color: #666; display: block;">Shift Load Modifier</label>
          <select onchange="updateAddWorkerTask(${idx}, 'modifier', parseFloat(this.value))" style="padding: 0.4rem; font-size: 0.85rem;">
            <option value="0.3" ${task.modifier === 0.3 ? 'selected' : ''}>0.3x (~30% load)</option>
            <option value="0.5" ${task.modifier === 0.5 ? 'selected' : ''}>0.5x</option>
            <option value="0.75" ${task.modifier === 0.75 ? 'selected' : ''}>0.75x</option>
            <option value="0.9" ${task.modifier === 0.9 ? 'selected' : ''}>0.9x</option>
            <option value="1.0" ${!task.modifier || task.modifier === 1.0 ? 'selected' : ''}>1.0x</option>
            <option value="1.1" ${task.modifier === 1.1 ? 'selected' : ''}>1.1x</option>
            <option value="1.2" ${task.modifier === 1.2 ? 'selected' : ''}>1.2x</option>
            <option value="1.25" ${task.modifier === 1.25 ? 'selected' : ''}>1.25x</option>
          </select>
        </div>

        <div style="min-width: 100px;">
          <label style="font-size: 0.75rem; color: #666; display: block;">Hrs Count</label>
          <label class="hours-toggle" title="Checked = hours count towards load balancing. Unchecked = hours do NOT count.">
            <input type="checkbox" onchange="updateAddWorkerTask(${idx}, 'counts_for_hours', this.checked); updateHoursToggleLabel(this)" ${task.counts_for_hours !== false ? 'checked' : ''}>
            <span class="hours-toggle-label ${task.counts_for_hours !== false ? 'counts' : 'no-count'}">${task.counts_for_hours !== false ? 'Counts' : 'No count'}</span>
          </label>
        </div>

        <div style="min-width: 115px;">
          <label style="font-size: 0.75rem; color: #666; display: block;">Training</label>
          <label class="hours-toggle" title="Checked = weighted skills stay as configured. Unchecked = weighted skills on this task become -1.">
            <input type="checkbox" id="add-worker-training-${idx}" onchange="updateAddWorkerTask(${idx}, 'training', this.checked); updateTrainingToggleLabel(this)" ${task.training !== false ? 'checked' : ''} ${isGapTask(task.task) ? 'disabled' : ''}>
            <span class="hours-toggle-label ${task.training !== false ? 'counts' : 'no-count'}" data-role="training-label">${task.training !== false ? 'Training on' : 'Training off'}</span>
          </label>
        </div>
      </div>

      <div style="margin-bottom:0.35rem;">
        <label style="font-size:0.8rem; font-weight:600;">Skills per modality</label>
      </div>
      <table class="worker-skill-table">
        <thead>
          <tr>
            <th class="modality-header">Modality</th>`;
    SKILLS.forEach(skill => {
      const skillSettings = SKILL_SETTINGS[skill] || {};
      const btnColor = skillSettings.button_color || '#6c757d';
      const textColor = skillSettings.text_color || '#fff';
      html += `<th><span class="skill-header" style="background:${btnColor}; color:${textColor};">${escapeHtml(skill)}</span></th>`;
    });
    html += `</tr>
        </thead>
        <tbody>`;
    MODALITIES.forEach(mod => {
      const modKey = mod.toLowerCase();
      const navColor = getModalityColor(modKey);
      const modSkills = task.skillsByModality[modKey] || {};
      html += `<tr>
        <td class="modality-header" style="color:${navColor}; font-weight:600;">${mod.toUpperCase()}</td>`;
      SKILLS.forEach(skill => {
        const skillVal = modSkills[skill] !== undefined ? modSkills[skill] : 0;
        const onchangeHandler = `updateAddWorkerSkill(${idx}, '${modKey}', '${skill}', this.value)`;
        html += `<td>${renderSkillSelect('', skillVal, onchangeHandler)}</td>`;
      });
      html += `</tr>`;
    });
    html += `</tbody>
      </table>
    </div>`;
  });

  container.innerHTML = html;
}

// Build skill color map from SKILL_SETTINGS
function buildSkillColorMap() {
  const colorMap = {};
  SKILLS.forEach(skill => {
    const settings = SKILL_SETTINGS[skill] || {};
    const rawSlug = settings.slug || skill.toLowerCase();
    const slug = rawSlug.replace(/[^a-z0-9-]/g, '-');
    colorMap[slug] = settings.button_color || '#6c757d';
  });
  return colorMap;
}

// Build skill slug map (skill name -> lowercase slug)
function buildSkillSlugMap() {
  const slugMap = {};
  SKILLS.forEach(skill => {
    const settings = SKILL_SETTINGS[skill] || {};
    const rawSlug = settings.slug || skill.toLowerCase();
    slugMap[skill] = rawSlug.replace(/[^a-z0-9-]/g, '-');
  });
  return slugMap;
}

// Convert entriesData format to timeline chart format
function convertToTimelineData(tab) {
  return TimelineFeed.convertGroupsToTimelineData(entriesData[tab] || [], {
    skills: SKILLS,
    normalizeSkillValue: normalizeSkillValueJS
  });
}

// Render timeline chart for a tab
function renderTimeline(tab) {
  const gridEl = document.getElementById(`timeline-grid-${tab}`);
  const headerEl = document.getElementById(`time-header-${tab}`);
  const legendEl = document.getElementById(`timeline-legend-${tab}`);

  if (!gridEl || typeof TimelineChart === 'undefined') {
    return;
  }

  // Convert data to timeline format
  const timelineData = convertToTimelineData(tab);

  // Build color and slug maps
  const skillColorMap = buildSkillColorMap();
  const skillSlugMap = buildSkillSlugMap();

  // Render timeline using shared module
  TimelineChart.render({
    gridEl: gridEl,
    headerEl: headerEl,
    data: timelineData,
    skillColumns: SKILLS,
    skillSlugMap: skillSlugMap,
    skillColorMap: skillColorMap,
    mergeModalities: true,  // Merge entries across modalities
    showCurrentTime: tab === 'today',  // Only show current time for today
    timeLineId: `current-time-line-${tab}`
  });

  // Build legend
  if (legendEl) {
    let legendHtml = SKILLS.map(skill => {
      const settings = SKILL_SETTINGS[skill] || {};
      const color = settings.button_color || '#6c757d';
      return `<div class="legend-item">
        <div class="legend-box" style="background: ${color};"></div>
        <span>${escapeHtml(skill)}</span>
      </div>`;
    }).join('');
    // Add gap legend entry
    legendHtml += `<div class="legend-item">
      <div class="legend-box legend-gap"></div>
      <span>Pause/Gap</span>
    </div>`;
    legendEl.innerHTML = legendHtml;
  }
}
