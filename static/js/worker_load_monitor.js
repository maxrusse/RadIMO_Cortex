// Worker Load Monitor JavaScript

const CONFIG = JSON.parse(document.getElementById('page-config').textContent);
const SKILLS = CONFIG.skills || [];
const MODALITIES = CONFIG.modalities || [];
const SKILL_SETTINGS = CONFIG.skill_settings || {};
const MODALITY_SETTINGS = CONFIG.modality_settings || {};
const LOAD_MONITOR_CONFIG = CONFIG.load_monitor_config || {};
const UI_COLORS = CONFIG.ui_colors || {};
const SKILL_MODALITY_WEIGHTS = CONFIG.skill_modality_weights || {};
window.WORKER_NAME_DISPLAY_STYLE = CONFIG.worker_name_display_style || 'first_last_id';
const MODES = ['simple', 'advanced-weight', 'advanced-count', 'flow', 'recent'];

let currentMode = MODES.includes(CONFIG.initial_mode) ? CONFIG.initial_mode : (LOAD_MONITOR_CONFIG.default_view || 'simple');
let workersData = [];
let workerLoadSummary = {};
let maxWeight = 0;
let maxLoadRatio = 0;
let autoRefreshInterval = null;
let flowDataLoaded = false;
let flowData = null;
let recentDataLoaded = false;
let recentData = [];
let recentFilters = { skill: '', modality: '', status: '', worker: '', visible: '50' };
let filters = { modality: '', skill: '', hideZero: false };
let sortState = {
  global: { column: 'weight_per_hour', direction: 'desc' },
  advancedWeight: { column: 'weight', direction: 'desc' },
  advancedCount: { column: 'count', direction: 'desc' },
};

(function injectDynamicColors() {
  const style = document.createElement('style');
  let css = '.load-low{background:#cfd8e3;}.load-blue{background:#2d7ac5;}';
  for (const [mod, settings] of Object.entries(MODALITY_SETTINGS)) {
    const navColor = settings.nav_color || '#6c757d';
    css += `.badge-${mod}{background:${navColor};}`;
    css += `.mod-header-${mod}{background:${navColor};color:white;}`;
  }
  for (const [skill, settings] of Object.entries(SKILL_SETTINGS)) {
    const btnColor = settings.button_color || '#6c757d';
    const textColor = settings.text_color || '#ffffff';
    const safeSkill = skill.toLowerCase().replace(/[^a-z0-9]/g, '-');
    css += `.skill-header-${safeSkill}{background:${btnColor};color:${textColor};}`;
  }
  style.textContent = css;
  document.head.appendChild(style);
})();

function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text == null ? '' : String(text);
  return div.innerHTML;
}

function formatValue(value, digits = 1) {
  return Number(value || 0).toFixed(digits);
}

function formatPercent(value) {
  return `${Math.round(Number(value || 0) * 100)}%`;
}

function formatDateTime(value) {
  if (!value) return '-';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleString();
}

function getSkillLabel(skill) {
  return SKILL_SETTINGS[skill]?.label || skill;
}

function getModalityLabel(modality) {
  return MODALITY_SETTINGS[modality]?.label || modality.toUpperCase();
}

function getSkillColor(skill) {
  return SKILL_SETTINGS[skill]?.button_color || '#5b7ea6';
}

function getModalityColor(modality) {
  return MODALITY_SETTINGS[modality]?.nav_color || '#6c757d';
}

function buildWorkerSortKey(name) {
  return window.WorkerNameUtils.buildSortKey(name);
}

function getValidWorkerThresholdHours() {
  return Number(workerLoadSummary?.valid_worker_threshold_hours || 1.0);
}

function getFilteredWorkers() {
  return workersData.filter(function(worker) {
    if (filters.hideZero && Number(worker.global_weight || 0) <= 0) {
      return false;
    }
    if (filters.modality && Number(worker.modalities?.[filters.modality]?.assignment_total || 0) <= 0) {
      return false;
    }
    if (filters.skill && Number(worker.skills?.[filters.skill] || 0) <= 0) {
      return false;
    }
    return true;
  });
}

function getValidWorkers(workers) {
  const threshold = getValidWorkerThresholdHours();
  return workers.filter(function(worker) {
    return Number(worker.hours_worked_now || 0) >= threshold;
  });
}

function getRatioBenchmark(workers) {
  const validWorkers = getValidWorkers(workers);
  const nonZeroRatios = validWorkers
    .map(function(worker) { return Number(worker.weight_per_hour || 0); })
    .filter(function(value) { return value > 0; })
    .sort(function(a, b) { return a - b; });
  if (!nonZeroRatios.length) return 0;
  const mid = Math.floor(nonZeroRatios.length / 2);
  if (nonZeroRatios.length % 2 === 0) {
    return (nonZeroRatios[mid - 1] + nonZeroRatios[mid]) / 2;
  }
  return nonZeroRatios[mid];
}

function computeBandStats(workers) {
  const validWorkers = getValidWorkers(workers);
  const benchmark = getRatioBenchmark(workers);
  const lowThreshold = benchmark * 0.8;
  const highThreshold = benchmark * 1.2;
  const overBandWorkers = validWorkers
    .filter(function(worker) { return Number(worker.weight_per_hour || 0) > highThreshold; })
    .sort(function(a, b) { return Number(b.weight_per_hour || 0) - Number(a.weight_per_hour || 0); });
  const underBandWorkers = validWorkers
    .filter(function(worker) { return Number(worker.weight_per_hour || 0) < lowThreshold; })
    .sort(function(a, b) { return Number(a.weight_per_hour || 0) - Number(b.weight_per_hour || 0); });
  return {
    validWorkers,
    benchmark,
    lowThreshold,
    highThreshold,
    overBandWorkers,
    underBandWorkers,
    inBandCount: Math.max(validWorkers.length - overBandWorkers.length - underBandWorkers.length, 0),
  };
}

function classifySystemStatus(bandStats, flowPayload) {
  const overflowQuote = Number(flowPayload?.summary?.overflow_quote || 0);

  if (!bandStats.validWorkers.length) {
    return { label: 'No Baseline', color: '#6c757d', note: 'No valid worker-hour baseline yet' };
  }
  if (overflowQuote >= 0.35) {
    return { label: 'Strained', color: '#b02a37', note: 'High overflow pressure in the current stream' };
  }
  if (overflowQuote >= 0.2) {
    return { label: 'Watch', color: '#856404', note: 'Meaningful overflow pressure needs attention' };
  }
  return { label: 'Stable', color: '#2d7a46', note: 'Overflow pressure remains low' };
}

function getRequestedSkillOverflowMetrics(flowPayload) {
  const bySkill = flowPayload?.summary?.by_requested_skill || {};
  return Object.entries(bySkill).map(function([skill, metrics]) {
    return {
      key: skill,
      label: getSkillLabel(skill),
      color: getSkillColor(skill),
      inflowWeight: Number(metrics.inflow_weight || 0),
      overflowWeight: Number(metrics.overflow_weight || 0),
      unresolvedWeight: Number(metrics.unresolved_weight || 0),
      count: Number(metrics.count || 0),
      overflowQuote: Number(metrics.overflow_quote || 0),
      unresolvedQuote: Number(metrics.unresolved_quote || 0),
    };
  }).filter(function(item) {
    return item.inflowWeight > 0 || item.overflowWeight > 0;
  }).sort(function(a, b) {
    if (b.overflowQuote !== a.overflowQuote) return b.overflowQuote - a.overflowQuote;
    return b.overflowWeight - a.overflowWeight;
  });
}

function getLoadThresholds(scaleMax = maxWeight) {
  const thresholds = LOAD_MONITOR_CONFIG.color_thresholds || {};
  const absConfig = thresholds.absolute || { low: 3.0, high: 7.0 };
  const lowThreshold = absConfig.low;
  const highThreshold = absConfig.high;
  return { lowThreshold, highThreshold };
}

function getLoadColor(weight, scaleMax = maxWeight) {
  const { lowThreshold, highThreshold } = getLoadThresholds(scaleMax);
  if (weight <= 0) return { bg: '#e9ecef', text: 'text-muted', fillClass: '' };
  if (weight < lowThreshold) return { bg: 'var(--load-green)', text: 'text-green', fillClass: 'load-green' };
  if (weight < highThreshold) return { bg: 'var(--load-yellow)', text: 'text-yellow', fillClass: 'load-yellow' };
  return { bg: 'var(--load-red)', text: 'text-red', fillClass: 'load-red' };
}

function getRatioColor(ratio, benchmark) {
  if (ratio <= 0) {
    return { text: 'text-muted', fillClass: '' };
  }
  if (benchmark <= 0) {
    return getLoadColor(ratio, maxLoadRatio);
  }
  const lowThreshold = benchmark * 0.8;
  const okThreshold = benchmark * 1.2;
  const highThreshold = benchmark * 1.5;
  if (ratio < lowThreshold) return { text: 'text-low', fillClass: 'load-low' };
  if (ratio <= okThreshold) return { text: 'text-green', fillClass: 'load-green' };
  if (ratio <= highThreshold) return { text: 'text-yellow', fillClass: 'load-yellow' };
  return { text: 'text-red', fillClass: 'load-red' };
}

function computeSkillMetrics(workers) {
  return SKILLS.map(function(skill) {
    const weightTotal = workers.reduce(function(sum, worker) {
      return sum + Number(worker.skill_weights?.[skill] || 0);
    }, 0);
    const hoursTotal = workers.reduce(function(sum, worker) {
      const isActive = Number(worker.skills?.[skill] || 0) > 0 || Number(worker.skill_weights?.[skill] || 0) > 0;
      return sum + (isActive ? Number(worker.hours_worked_now || 0) : 0);
    }, 0);
    const activeWorkers = workers.reduce(function(sum, worker) {
      const isActive = Number(worker.skills?.[skill] || 0) > 0 || Number(worker.skill_weights?.[skill] || 0) > 0;
      return sum + (isActive ? 1 : 0);
    }, 0);
    return {
      key: skill,
      label: getSkillLabel(skill),
      color: getSkillColor(skill),
      weightTotal,
      hoursTotal,
      weightPerHour: hoursTotal > 0 ? weightTotal / hoursTotal : 0,
      activeWorkers,
      assignments: workers.reduce(function(sum, worker) {
        return sum + Number(worker.skills?.[skill] || 0);
      }, 0),
    };
  });
}

function computeModalityMetrics(workers) {
  return MODALITIES.map(function(modality) {
    const weightTotal = workers.reduce(function(sum, worker) {
      return sum + Number(worker.modalities?.[modality]?.weighted_total || 0);
    }, 0);
    const hoursTotal = workers.reduce(function(sum, worker) {
      const isActive = Number(worker.modalities?.[modality]?.assignment_total || 0) > 0 || Number(worker.modalities?.[modality]?.weighted_total || 0) > 0;
      return sum + (isActive ? Number(worker.hours_worked_now || 0) : 0);
    }, 0);
    const activeWorkers = workers.reduce(function(sum, worker) {
      const isActive = Number(worker.modalities?.[modality]?.assignment_total || 0) > 0 || Number(worker.modalities?.[modality]?.weighted_total || 0) > 0;
      return sum + (isActive ? 1 : 0);
    }, 0);
    return {
      key: modality,
      label: getModalityLabel(modality),
      color: getModalityColor(modality),
      weightTotal,
      hoursTotal,
      weightPerHour: hoursTotal > 0 ? weightTotal / hoursTotal : 0,
      activeWorkers,
      assignments: workers.reduce(function(sum, worker) {
        return sum + Number(worker.modalities?.[modality]?.assignment_total || 0);
      }, 0),
    };
  });
}

function renderCardGrid(containerId, cards, emptyMessage, isCompact = false) {
  const container = document.getElementById(containerId);
  if (!container) return;
  if (!cards.length) {
    container.innerHTML = `<div class="summary-card-empty">${escapeHtml(emptyMessage)}</div>`;
    return;
  }

  container.innerHTML = cards.map(function(card) {
    const badgeClass = card.softBadge ? 'summary-card-badge is-soft' : 'summary-card-badge';
    const color = card.color || '#6c757d';
    return `<div class="summary-card">
      <div class="summary-card-header">
        <span class="summary-card-title">${escapeHtml(card.title || card.label || '')}</span>
        ${card.badge == null ? '' : `<span class="${badgeClass}" style="background:${color};">${escapeHtml(card.badge)}</span>`}
      </div>
      <div class="summary-card-main">${escapeHtml(card.main)}</div>
      ${card.mainSub ? `<div class="summary-card-main-sub">${escapeHtml(card.mainSub)}</div>` : ''}
      <div class="summary-card-main-label">${escapeHtml(card.mainLabel || '')}</div>
      ${(card.subRows || []).map(function(row, index) {
        const extraClass = index === 0 ? 'summary-card-sub summary-card-sub-stack' : 'summary-card-sub';
        return `<div class="${extraClass}">
          <span>${escapeHtml(row.left)}</span>
          <span>${escapeHtml(row.right)}</span>
        </div>`;
      }).join('')}
    </div>`;
  }).join('');
}

function renderOverviewCards(workers) {
  return workers;
}

function renderSkillCards(workers, containerId, emptyMessage, compact = false) {
  const metrics = computeSkillMetrics(workers);
  const sorted = [...metrics].sort(function(a, b) { return b.weightPerHour - a.weightPerHour; });
  const cards = sorted.map(function(metric) {
    return {
      title: metric.label,
      badge: `${metric.activeWorkers} active`,
      color: metric.color,
      main: formatValue(metric.weightPerHour, 2),
      mainLabel: 'Weight / Hour',
      subRows: [
        { left: 'Weighted total', right: formatValue(metric.weightTotal) },
        { left: 'Assignments', right: String(metric.assignments) },
      ],
    };
  });
  renderCardGrid(containerId, cards, emptyMessage, compact);
}

function renderModalityCards(workers, containerId, emptyMessage, compact = false) {
  const metrics = computeModalityMetrics(workers);
  const sorted = [...metrics].sort(function(a, b) { return b.weightPerHour - a.weightPerHour; });
  const cards = sorted.map(function(metric) {
    return {
      title: metric.label,
      badge: `${metric.activeWorkers} active`,
      color: metric.color,
      main: formatValue(metric.weightPerHour, 2),
      mainLabel: 'Weight / Hour',
      subRows: [
        { left: 'Weighted total', right: formatValue(metric.weightTotal) },
        { left: 'Assignments', right: String(metric.assignments) },
      ],
    };
  });
  renderCardGrid(containerId, cards, emptyMessage, compact);
}

function getSortValue(worker, column, tableType) {
  if (column === 'name') return buildWorkerSortKey(worker.name);
  if (column === 'balance_weight') return Number(worker.balance_weight || 0);
  if (column === 'manual_adjustment') return Number(worker.manual_adjustment || 0);
  if (tableType === 'advancedCount') {
    if (column === 'count') {
      return getDerivedWorkerCount(worker);
    }
  }
  if (tableType === 'advancedWeight') {
    if (column === 'weight') {
      return getDerivedWorkerWeight(worker);
    }
  }
  if (column === 'weight') return Number(worker.global_weight || 0);
  if (column === 'weight_per_hour') return Number(worker.weight_per_hour || 0);
  return 0;
}

function sortWorkers(workers, tableType) {
  const state = sortState[tableType];
  const sorted = [...workers];
  const ascending = state.direction === 'asc';
  sorted.sort(function(a, b) {
    const valA = getSortValue(a, state.column, tableType);
    const valB = getSortValue(b, state.column, tableType);
    if (typeof valA === 'string' || typeof valB === 'string') {
      return ascending ? String(valA).localeCompare(String(valB)) : String(valB).localeCompare(String(valA));
    }
    return ascending ? valA - valB : valB - valA;
  });
  return sorted;
}

function sortTable(tableType, column) {
  const state = sortState[tableType];
  if (!state) return;
  if (state.column === column) {
    state.direction = state.direction === 'asc' ? 'desc' : 'asc';
  } else {
    state.column = column;
    state.direction = column === 'name' ? 'asc' : 'desc';
  }
  renderAllTables();
}

function updateSortIndicators(tableType, tableId) {
  const state = sortState[tableType];
  if (!state) return;
  document.querySelectorAll(`#${tableId} th`).forEach(function(th) {
    th.classList.remove('sort-asc', 'sort-desc');
    if (th.dataset.sort === state.column) {
      th.classList.add(state.direction === 'asc' ? 'sort-asc' : 'sort-desc');
    }
  });
}

function getVisibleModalities() {
  return filters.modality ? [filters.modality] : MODALITIES;
}

function getVisibleSkills() {
  return filters.skill ? [filters.skill] : SKILLS;
}

function getCellCount(worker, modality, skill) {
  return Number(worker.modalities?.[modality]?.skill_counts?.[skill] || 0);
}

function getConfiguredSkillModalityWeight(skill, modality) {
  return Number(SKILL_MODALITY_WEIGHTS?.[modality]?.[skill] || 0);
}

function getCellDerivedWeight(worker, modality, skill) {
  return getCellCount(worker, modality, skill) * getConfiguredSkillModalityWeight(skill, modality);
}

function getDerivedWorkerCount(worker) {
  return MODALITIES.reduce(function(total, modality) {
    return total + SKILLS.reduce(function(skillTotal, skill) {
      return skillTotal + getCellCount(worker, modality, skill);
    }, 0);
  }, 0);
}

function getDerivedWorkerWeight(worker) {
  return MODALITIES.reduce(function(total, modality) {
    return total + SKILLS.reduce(function(skillTotal, skill) {
      return skillTotal + getCellDerivedWeight(worker, modality, skill);
    }, 0);
  }, 0);
}

function renderGlobalTable() {
  const tbody = document.getElementById('tbody-global');
  if (!tbody) return;

  const filteredWorkers = getFilteredWorkers();
  const sorted = sortWorkers(filteredWorkers, 'global');
  if (!sorted.length) {
    tbody.innerHTML = '<tr><td colspan="6" class="no-data">No workers match filters</td></tr>';
    return;
  }

  const maxBarRatio = Math.max(maxLoadRatio, 1);
  const benchmark = getRatioBenchmark(filteredWorkers);
  let html = '';
  let totalBalance = 0;
  let totalManual = 0;
  let totalWeight = 0;
  let totalHours = 0;

  sorted.forEach(function(worker) {
    const balanceWeight = Number(worker.balance_weight || 0);
    const manualAdjustment = Number(worker.manual_adjustment || 0);
    const weight = Number(worker.global_weight || 0);
    const hours = Number(worker.hours_worked_now || 0);
    const ratio = Number(worker.weight_per_hour || 0);
    totalBalance += balanceWeight;
    totalManual += manualAdjustment;
    totalWeight += weight;
    totalHours += hours;
    const ratioColor = getRatioColor(ratio, benchmark);
    const barWidth = Math.min((ratio / maxBarRatio) * 100, 100);
    html += `<tr>
      <td class="worker-col">${escapeHtml(worker.name)}</td>
      <td class="weight-value">${formatValue(balanceWeight)}</td>
      <td class="weight-value ${manualAdjustment > 0 ? 'text-red' : (manualAdjustment < 0 ? 'text-green' : 'text-muted')}">${manualAdjustment > 0 ? '+' : ''}${formatValue(manualAdjustment)}</td>
      <td class="weight-value ${getLoadColor(weight).text}">${formatValue(weight)}</td>
      <td class="weight-value ${ratioColor.text}">${formatValue(ratio, 2)}</td>
      <td>
        <div class="weight-bar">
          <div class="weight-bar-fill ${ratioColor.fillClass}" style="width:${barWidth}%;max-width:200px;"></div>
        </div>
      </td>
    </tr>`;
  });

  const totalRatio = totalHours > 0 ? totalWeight / totalHours : 0;
  const totalColor = getRatioColor(totalRatio, benchmark);
  const totalBarWidth = Math.min((totalRatio / maxBarRatio) * 100, 100);
  html += `<tr class="totals-row">
    <td class="worker-col">Total</td>
    <td class="weight-value">${formatValue(totalBalance)}</td>
    <td class="weight-value ${totalManual > 0 ? 'text-red' : (totalManual < 0 ? 'text-green' : '')}">${totalManual > 0 ? '+' : ''}${formatValue(totalManual)}</td>
    <td class="weight-value">${formatValue(totalWeight)}</td>
    <td class="weight-value ${totalColor.text}">${formatValue(totalRatio, 2)}</td>
    <td>
      <div class="weight-bar">
        <div class="weight-bar-fill ${totalColor.fillClass}" style="width:${totalBarWidth}%;max-width:200px;"></div>
      </div>
    </td>
  </tr>`;
  tbody.innerHTML = html;
}

function renderAdvancedTable(variant) {
  const safeVariant = variant === 'weight' ? 'weight' : 'count';
  const tableKey = safeVariant === 'weight' ? 'advancedWeight' : 'advancedCount';
  const tableId = safeVariant === 'weight' ? 'table-advanced-weight' : 'table-advanced-count';
  const thead = document.getElementById(`thead-advanced-${safeVariant}`);
  const tbody = document.getElementById(`tbody-advanced-${safeVariant}`);
  if (!thead || !tbody) return;

  const filteredWorkers = getFilteredWorkers();
  const sorted = sortWorkers(filteredWorkers, tableKey);
  const showModalities = getVisibleModalities();
  const showSkills = getVisibleSkills();

  let headerTop = `<tr class="header-top"><th rowspan="2" class="sortable worker-col" data-sort="name" onclick="sortTable('${tableKey}', 'name')">Worker</th>`;
  let headerSub = '<tr class="header-sub">';

  showModalities.forEach(function(modality) {
    headerTop += `<th colspan="${showSkills.length}" class="mod-header-${modality}">${escapeHtml(getModalityLabel(modality))}</th>`;
    showSkills.forEach(function(skill) {
      const safeSkill = skill.toLowerCase().replace(/[^a-z0-9]/g, '-');
      headerSub += `<th class="skill-header-${safeSkill}" title="${escapeHtml(getSkillLabel(skill))}">${escapeHtml(getSkillLabel(skill))}</th>`;
    });
  });

  const totalSortKey = safeVariant === 'weight' ? 'weight' : 'count';
  const totalLabel = safeVariant === 'weight' ? 'Derived Total' : 'Total';
  headerTop += `<th rowspan="2" class="sortable" data-sort="${totalSortKey}" onclick="sortTable('${tableKey}', '${totalSortKey}')">${totalLabel}</th></tr>`;
  headerSub += '</tr>';
  thead.innerHTML = headerTop + headerSub;

  if (!sorted.length) {
    tbody.innerHTML = `<tr><td colspan="${(showModalities.length * showSkills.length) + 2}" class="no-data">No workers match filters</td></tr>`;
    updateSortIndicators(tableKey, tableId);
    return;
  }

  const benchmark = getRatioBenchmark(filteredWorkers);
  const totals = {};
  showModalities.forEach(function(modality) {
    totals[modality] = {};
    showSkills.forEach(function(skill) {
      totals[modality][skill] = 0;
    });
  });

  let grandTotal = 0;
  let html = '';
  sorted.forEach(function(worker) {
    html += '<tr>';
    html += `<td class="worker-col">${escapeHtml(worker.name)}</td>`;
    let rowTotal = 0;

    showModalities.forEach(function(modality) {
      showSkills.forEach(function(skill) {
        const value = safeVariant === 'weight' ? getCellDerivedWeight(worker, modality, skill) : getCellCount(worker, modality, skill);
        totals[modality][skill] += value;
        rowTotal += value;
        const color = safeVariant === 'weight' ? getLoadColor(value) : getLoadColor(value, Math.max(maxWeight, 1));
        html += value > 0
          ? `<td class="${color.text}" style="font-weight:600;">${safeVariant === 'weight' ? formatValue(value, 1) : String(value)}</td>`
          : '<td style="color:#ccc;">-</td>';
      });
    });

    grandTotal += rowTotal;
    const totalColor = safeVariant === 'weight' ? getRatioColor(Number(worker.weight_per_hour || 0), benchmark) : getLoadColor(rowTotal, Math.max(maxWeight, 1));
    html += `<td class="${totalColor.text}" style="font-weight:700;">${safeVariant === 'weight' ? formatValue(rowTotal, 1) : String(rowTotal)}</td>`;
    html += '</tr>';
  });

  html += '<tr class="totals-row"><td class="worker-col">Total</td>';
  showModalities.forEach(function(modality) {
    showSkills.forEach(function(skill) {
      const value = totals[modality][skill];
      html += `<td>${value > 0 ? (safeVariant === 'weight' ? formatValue(value, 1) : String(value)) : '-'}</td>`;
    });
  });
  html += `<td>${safeVariant === 'weight' ? formatValue(grandTotal, 1) : String(grandTotal)}</td></tr>`;
  tbody.innerHTML = html;
  updateSortIndicators(tableKey, tableId);
}

function renderRecentTable() {
  const tbody = document.getElementById('tbody-recent');
  const summary = document.getElementById('recent-summary-note');
  if (!tbody) return;
  if (!recentData.length) {
    if (summary) {
      summary.textContent = 'Showing 0 of 0 events';
    }
    tbody.innerHTML = '<tr><td colspan="7" class="no-data">No recent distributions recorded yet.</td></tr>';
    return;
  }
  const filtered = recentData.filter(function(item) {
    const status = item.unresolved ? 'unresolved' : (item.overflowed ? 'overflow' : 'direct');
    const workerName = String(item.person || '').toLowerCase();
    const workerRawName = String(item.person_raw || '').toLowerCase();
    const requestedSkill = String(item.requested_skill || '');
    const actualSkill = String(item.actual_skill || '');
    const requestedModality = String(item.requested_modality || '');
    const actualModality = String(item.actual_modality || '');
    if (recentFilters.worker && !workerName.includes(recentFilters.worker) && !workerRawName.includes(recentFilters.worker)) {
      return false;
    }
    if (recentFilters.status && status !== recentFilters.status) {
      return false;
    }
    if (recentFilters.skill && requestedSkill !== recentFilters.skill && actualSkill !== recentFilters.skill) {
      return false;
    }
    if (recentFilters.modality && requestedModality !== recentFilters.modality && actualModality !== recentFilters.modality) {
      return false;
    }
    return true;
  });

  const visibleCount = recentFilters.visible === 'full' ? filtered.length : Math.max(parseInt(recentFilters.visible, 10) || 0, 0);
  const visibleItems = recentFilters.visible === 'full' ? filtered : filtered.slice(0, visibleCount);
  if (summary) {
    const visibleLabel = recentFilters.visible === 'full' ? 'Full day stream' : `${visibleItems.length} visible`;
    summary.textContent = `${visibleLabel} | showing ${visibleItems.length} of ${filtered.length} filtered events (${recentData.length} loaded)`;
  }
  if (!visibleItems.length) {
    tbody.innerHTML = '<tr><td colspan="7" class="no-data">No recent events match the current filters.</td></tr>';
    return;
  }
  tbody.innerHTML = visibleItems.map(function(item) {
    const requested = `${getSkillLabel(item.requested_skill)} / ${getModalityLabel(item.requested_modality)}`;
    const actual = `${getSkillLabel(item.actual_skill)} / ${getModalityLabel(item.actual_modality)}`;
    let status = '<span class="recent-pill recent-pill-ok">Direct</span>';
    if (item.unresolved) {
      status = '<span class="recent-pill recent-pill-unresolved">Unresolved</span>';
    } else if (item.overflowed) {
      status = '<span class="recent-pill recent-pill-overflow">Overflow</span>';
    }
    return `<tr>
      <td>${escapeHtml(formatDateTime(item.timestamp))}</td>
      <td>${escapeHtml(item.person || '-')}</td>
      <td>${escapeHtml(requested)}</td>
      <td>${escapeHtml(actual)}</td>
      <td>${escapeHtml(item.task_label || '-')}</td>
      <td>${formatValue(item.weight, 2)}</td>
      <td>${status}</td>
    </tr>`;
  }).join('');
}

function filterRecentByWorker(value) {
  recentFilters.worker = String(value || '').trim().toLowerCase();
  if (currentMode === 'recent') {
    renderRecentTable();
  }
}

function filterRecentByStatus(value) {
  recentFilters.status = value || '';
  if (currentMode === 'recent') {
    renderRecentTable();
  }
}

function filterRecentBySkill(value) {
  recentFilters.skill = value || '';
  if (currentMode === 'recent') {
    renderRecentTable();
  }
}

function filterRecentByModality(value) {
  recentFilters.modality = value || '';
  if (currentMode === 'recent') {
    renderRecentTable();
  }
}

function setRecentVisibleCount(value) {
  recentFilters.visible = value || '50';
  if (currentMode === 'recent') {
    renderRecentTable();
  }
}

function renderWorkerLoadPanels() {
  const filteredWorkers = getFilteredWorkers();

  if (currentMode === 'simple') {
    renderGlobalTable();
    updateSortIndicators('global', 'table-global');
    return;
  }
  if (currentMode === 'advanced-weight') {
    renderAdvancedTable('weight');
    return;
  }
  if (currentMode === 'advanced-count') {
    renderAdvancedTable('count');
    return;
  }
  if (currentMode === 'recent') {
    renderRecentTable();
    return;
  }
  if (currentMode === 'flow' && flowDataLoaded) {
    renderFlowDataState(flowData);
  }
}

function renderAllTables() {
  renderWorkerLoadPanels();
  const noDataMsg = document.getElementById('no-data-msg');
  if (noDataMsg) {
    noDataMsg.style.display = workersData.length === 0 && currentMode !== 'flow' ? 'block' : 'none';
  }
}

function setMode(mode, options = {}) {
  const skipLoad = options.skipLoad === true;
  currentMode = MODES.includes(mode) ? mode : 'simple';
  MODES.forEach(function(modeName) {
    document.body.classList.remove(`mode-${modeName}`);
  });
  document.body.classList.add(`mode-${currentMode}`);
  document.querySelectorAll('.mode-btn').forEach(function(btn) {
    btn.classList.toggle('active', btn.dataset.mode === currentMode);
  });
  renderAllTables();
  if (skipLoad) {
    return;
  }
  if (currentMode === 'flow' && !flowDataLoaded) {
    loadFlowData();
  }
  if (currentMode === 'recent') {
    loadRecentData();
  }
}

function filterByModality(modality) {
  filters.modality = modality;
  document.querySelectorAll('[data-modality]').forEach(function(btn) {
    btn.classList.toggle('active', btn.dataset.modality === modality);
  });
  renderAllTables();
}

function filterBySkill(skill) {
  filters.skill = skill;
  document.querySelectorAll('[data-skill]').forEach(function(btn) {
    btn.classList.toggle('active', btn.dataset.skill === skill);
  });
  renderAllTables();
}

function applyFilters() {
  filters.hideZero = document.getElementById('filter-hide-zero')?.checked || false;
  renderAllTables();
}

function toggleAutoRefresh() {
  const checkbox = document.getElementById('auto-refresh');
  if (autoRefreshInterval) {
    clearInterval(autoRefreshInterval);
    autoRefreshInterval = null;
  }
  if (checkbox?.checked) {
    refreshCurrentMode();
    autoRefreshInterval = setInterval(refreshCurrentMode, 30000);
  }
}

function updateLastUpdateTime() {
  const lastUpdate = document.getElementById('last-update');
  if (lastUpdate) {
    lastUpdate.textContent = `Updated: ${new Date().toLocaleTimeString()}`;
  }
}

function loadData() {
  return fetch('/api/worker-load/data')
    .then(function(response) {
      if (!response.ok) throw new Error(`Failed to load worker data (${response.status})`);
      return response.json();
    })
    .then(function(data) {
      if (!data.success) {
        throw new Error(data.error || 'Worker load data request failed');
      }
      workersData = data.workers || [];
      workerLoadSummary = data.summary || {};
      maxWeight = Number(data.max_weight || 0);
      maxLoadRatio = Number(data.max_weight_per_hour || 0);
      updateLastUpdateTime();
      renderAllTables();
    })
    .catch(function(error) {
      console.error('Error loading worker data:', error);
    });
}

function loadRecentData() {
  return fetch('/api/worker-load/recent-distributions')
    .then(function(response) {
      if (!response.ok) throw new Error(`Recent distributions request failed (${response.status})`);
      return response.json();
    })
    .then(function(data) {
      if (!data.success) {
        throw new Error(data.error || 'Recent distributions request failed');
      }
      recentData = data.items || data.events || [];
      recentDataLoaded = true;
      if (currentMode === 'recent') {
        renderRecentTable();
      }
    })
    .catch(function(error) {
      console.error('Failed to load recent distributions:', error);
    });
}

function formatFlowValue(value) {
  const numeric = Number(value || 0);
  return numeric.toFixed(numeric % 1 === 0 ? 0 : 1);
}

function dataSkillLabel(skillKey, data) {
  return data?.skill_labels?.[skillKey] || getSkillLabel(skillKey);
}

function getFlowLinks(data) {
  return (data.links || []).filter(function(link) {
    return Number(link.weight || 0) > 0 && link.from && link.to;
  });
}

function renderFlowDiagram(data) {
  const svg = document.getElementById('flow-diagram');
  const emptyState = document.getElementById('flow-diagram-empty');
  if (!svg || !emptyState) return;

  const links = getFlowLinks(data);
  if (!links.length) {
    svg.innerHTML = '';
    svg.setAttribute('height', '0');
    emptyState.style.display = 'block';
    return;
  }
  emptyState.style.display = 'block';
  emptyState.style.display = 'none';

  const activeSkills = (data.skills || []).filter(function(skill) {
    const totals = data.totals?.[skill] || {};
    return Number(totals.out_total || 0) > 0 || Number(totals.in_total || 0) > 0;
  });

  const width = 960;
  const leftX = 120;
  const rightX = 760;
  const nodeWidth = 120;
  const rowHeight = 28;
  const rowGap = 10;
  const topPadding = 42;
  const bottomPadding = 24;

  function layoutSide(skillList, totalKey) {
    const skillOrder = SKILLS.filter(function(skill) { return skillList.includes(skill); });
    skillList.forEach(function(skill) {
      if (!skillOrder.includes(skill)) skillOrder.push(skill);
    });
    let cursorY = topPadding;
    const nodes = [];
    skillOrder.forEach(function(skill) {
      const totals = data.totals?.[skill] || {};
      const total = Number(totals[totalKey] || 0);
      if (total <= 0) return;
      nodes.push({
        skill,
        y: cursorY,
        centerY: cursorY + (rowHeight / 2),
        total,
        color: getSkillColor(skill),
        label: dataSkillLabel(skill, data),
      });
      cursorY += rowHeight + rowGap;
    });
    return { nodes, height: cursorY - rowGap + bottomPadding };
  }

  const leftLayout = layoutSide(activeSkills, 'out_total');
  const rightLayout = layoutSide(activeSkills, 'in_total');
  const height = Math.max(leftLayout.height, rightLayout.height, 220);
  const leftPos = {};
  const rightPos = {};
  leftLayout.nodes.forEach(function(node) { leftPos[node.skill] = node; });
  rightLayout.nodes.forEach(function(node) { rightPos[node.skill] = node; });

  const maxLinkWeight = Math.max.apply(null, links.map(function(link) { return Number(link.weight || 0); }));
  const scaleWidth = function(weight) {
    return 2 + ((weight / Math.max(maxLinkWeight, 1)) * 14);
  };

  const linkSvg = links
    .sort(function(a, b) { return Number(a.weight || 0) - Number(b.weight || 0); })
    .map(function(link) {
      const source = leftPos[link.from];
      const target = rightPos[link.to];
      if (!source || !target) return '';
      const sourceX = leftX + nodeWidth;
      const targetX = rightX;
      const sourceY = source.centerY;
      const targetY = target.centerY;
      const controlOffset = Math.max((targetX - sourceX) * 0.35, 120);
      const stroke = getSkillColor(source.skill);
      const tooltip = `${source.label} -> ${target.label}: ${formatFlowValue(link.weight)}`;
      return `
        <path d="M ${sourceX} ${sourceY} C ${sourceX + controlOffset} ${sourceY}, ${targetX - controlOffset} ${targetY}, ${targetX} ${targetY}"
          fill="none"
          stroke="${stroke}"
          stroke-width="${scaleWidth(Number(link.weight || 0))}"
          stroke-linecap="round"
          opacity="0.34">
          <title>${escapeHtml(tooltip)}</title>
        </path>
      `;
    }).join('');

  function renderNodes(nodes, x, align) {
    return nodes.map(function(node) {
      const textX = align === 'left' ? x + 10 : x + nodeWidth - 10;
      const anchor = align === 'left' ? 'start' : 'end';
      const totalX = align === 'left' ? x + nodeWidth - 10 : x + 10;
      const totalAnchor = align === 'left' ? 'end' : 'start';
      return `
        <g>
          <rect x="${x}" y="${node.y}" width="${nodeWidth}" height="${rowHeight}" rx="7" fill="#ffffff" stroke="${node.color}" stroke-width="1.2"></rect>
          <text x="${textX}" y="${node.y + 18}" font-size="11" font-weight="700" fill="#243447" text-anchor="${anchor}">${escapeHtml(node.label)}</text>
          <text x="${totalX}" y="${node.y + 18}" font-size="11" font-weight="700" fill="${node.color}" text-anchor="${totalAnchor}">${formatFlowValue(node.total)}</text>
          <title>${escapeHtml(node.label)}</title>
        </g>
      `;
    }).join('');
  }

  svg.setAttribute('viewBox', `0 0 ${width} ${height}`);
  svg.setAttribute('width', String(width));
  svg.setAttribute('height', String(height));
  svg.innerHTML = `
    <rect x="0" y="0" width="${width}" height="${height}" fill="#ffffff"></rect>
    <text x="${leftX}" y="22" font-size="13" font-weight="700" fill="#004892">Requested Skill</text>
    <text x="${rightX + nodeWidth}" y="22" font-size="13" font-weight="700" text-anchor="end" fill="#004892">Absorbing Target Skill</text>
    ${linkSvg}
    ${renderNodes(leftLayout.nodes, leftX, 'left')}
    ${renderNodes(rightLayout.nodes, rightX, 'right')}
  `;
}

function updateFlowMeta(data) {
  const summary = data.summary || {};
  const setText = function(id, value) {
    const element = document.getElementById(id);
    if (element) element.textContent = value;
  };
  setText('meta-window', data.meta?.window || '-');
  setText('meta-reset-date', data.meta?.last_reset_date || '-');
  setText('meta-total', formatFlowValue(data.grand_totals?.cross_pool_total || 0));
  setText('meta-inflow', formatFlowValue(summary.total_inflow_weight || 0));
  setText('meta-overflow-quote', formatPercent(summary.overflow_quote || 0));
  setText('meta-unresolved', formatFlowValue(summary.unresolved_weight_total || 0));
  setText('meta-unresolved-quote', formatPercent(summary.unresolved_quote || 0));
  updateLastUpdateTime();
}

function renderFlowDataState(data) {
  if (!data) return;
  updateFlowMeta(data);
  renderFlowDiagram(data);
  const noDataMsg = document.getElementById('flow-no-data-msg');
  if (noDataMsg) {
    noDataMsg.style.display = getFlowLinks(data).length ? 'none' : 'block';
  }
}

function loadFlowData() {
  return fetch('/api/flow-balance/data')
    .then(function(response) {
      if (!response.ok) throw new Error(`Flow data request failed (${response.status})`);
      return response.json();
    })
    .then(function(data) {
      flowData = data;
      flowDataLoaded = true;
      if (currentMode === 'flow') {
        renderFlowDataState(data);
        return;
      }
      renderAllTables();
    })
    .catch(function(error) {
      console.error('Failed to load flow data:', error);
    });
}

function refreshCurrentMode() {
  const requests = [loadData(), loadFlowData()];
  if (currentMode === 'recent') {
    requests.push(loadRecentData());
  }
  return Promise.all(requests);
}

document.addEventListener('DOMContentLoaded', function() {
  setMode(currentMode, { skipLoad: true });
  toggleAutoRefresh();
});
