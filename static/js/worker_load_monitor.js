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
let recentFilters = { skill: '', modality: '', status: '', worker: '', visible: '50', type: '' };
let correctionWorkers = [];
let correctionDeltas = [];
let correctionLog = [];
let correctionsLoaded = false;
let expandedWorkerId = null;
let filters = { modality: '', skill: '', hideZero: false };
let sortState = {
  global: { column: 'deviation', direction: 'desc' },
  advancedWeight: { column: 'weight', direction: 'desc' },
  advancedCount: { column: 'count', direction: 'desc' },
};

(function injectDynamicColors() {
  const style = document.createElement('style');
  let css = '.load-low{background:#cfd8e3;}.load-blue{background:#2d7ac5;}';
  for (const [mod, settings] of Object.entries(MODALITY_SETTINGS)) {
    const navColor = settings.nav_color || '#6c757d';
    css += `.badge-${mod}{background:${navColor};}`;
    css += `.load-table .mod-header-${mod}{background:${navColor}!important;color:white!important;border-bottom:4px solid rgba(0,0,0,.22);}`;
  }
  for (const [skill, settings] of Object.entries(SKILL_SETTINGS)) {
    const btnColor = settings.button_color || '#6c757d';
    const textColor = settings.text_color || '#ffffff';
    const safeSkill = skill.toLowerCase().replace(/[^a-z0-9]/g, '-');
    css += `.load-table .skill-header-${safeSkill}{background:${btnColor}!important;color:${textColor}!important;border-radius:999px 999px 0 0;}`;
  }
  style.textContent = css;
  document.head.appendChild(style);
})();

function t(text) {
  return window.RadimoI18n?.t ? window.RadimoI18n.t(text) : text;
}

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
  if (column === 'hours') return Number(worker.hours_worked_now || 0);
  if (column === 'deviation') {
    const deviation = getWorkerDeviation(worker, getRatioBenchmark(workersData));
    return deviation === null ? -Infinity : deviation;
  }
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

function getWorkerDeviation(worker, benchmark) {
  const hours = Number(worker.hours_worked_now || 0);
  if (!benchmark || hours < getValidWorkerThresholdHours()) return null;
  return Number(worker.weight_per_hour || 0) / benchmark - 1;
}

function formatDeviation(deviation) {
  if (deviation === null) return '–';
  const percent = Math.round(deviation * 100);
  return `${percent > 0 ? '+' : ''}${percent} %`;
}

function deviationBar(deviation) {
  if (deviation === null) return '<div class="dev-bar"></div>';
  const clamped = Math.max(-1, Math.min(1, deviation));
  const width = Math.abs(clamped) * 50;
  const left = clamped < 0 ? 50 - width : 50;
  let tone = 'is-ok';
  if (deviation > 0.5) tone = 'is-veryhigh';
  else if (deviation > 0.2) tone = 'is-high';
  else if (deviation < -0.2) tone = 'is-low';
  return `<div class="dev-bar"><div class="dev-bar__fill ${tone}" style="left:${left}%;width:${Math.max(width, 0.6)}%"></div></div>`;
}

function renderGlobalTable() {
  const tbody = document.getElementById('tbody-global');
  if (!tbody) return;
  const thresholdEl = document.getElementById('valid-threshold');
  if (thresholdEl) thresholdEl.textContent = formatValue(getValidWorkerThresholdHours(), 1);

  const filteredWorkers = getFilteredWorkers();
  const sorted = sortWorkers(filteredWorkers, 'global');
  const preservedDetail = document.querySelector('#tbody-global tr.detail-row');
  if (!sorted.length) {
    tbody.innerHTML = `<tr><td colspan="7" class="no-data">${escapeHtml(t('No workers match filters'))}</td></tr>`;
    return;
  }

  const benchmark = getRatioBenchmark(workersData);
  let html = '';
  let totals = { hours: 0, balance: 0, manual: 0, weight: 0 };

  sorted.forEach(function(worker) {
    const balanceWeight = Number(worker.balance_weight || 0);
    const manualAdjustment = Number(worker.manual_adjustment || 0);
    const weight = Number(worker.global_weight || 0);
    const hours = Number(worker.hours_worked_now || 0);
    const ratio = Number(worker.weight_per_hour || 0);
    totals.hours += hours;
    totals.balance += balanceWeight;
    totals.manual += manualAdjustment;
    totals.weight += weight;
    const deviation = getWorkerDeviation(worker, benchmark);
    const ratioColor = getRatioColor(ratio, benchmark);
    const workerId = String(worker.canonical_id || worker.name || '');
    const isOpen = expandedWorkerId === workerId;
    const belowThreshold = hours < getValidWorkerThresholdHours();
    html += `<tr class="worker-row${isOpen ? ' is-open' : ''}${belowThreshold ? ' is-below-threshold' : ''}" data-worker-id="${escapeHtml(workerId)}"
      onclick="toggleWorkerDetail(this.dataset.workerId)" title="${escapeHtml(t('Click for details and corrections'))}">
      <td class="worker-col">${escapeHtml(worker.name)}</td>
      <td class="weight-value">${formatValue(hours, 2)}</td>
      <td class="weight-value">${formatValue(balanceWeight, 2)}</td>
      <td class="weight-value ${manualAdjustment > 0 ? 'text-red' : (manualAdjustment < 0 ? 'text-green' : 'text-muted')}">${manualAdjustment > 0 ? '+' : ''}${formatValue(manualAdjustment, 2)}</td>
      <td class="weight-value">${formatValue(weight, 2)}</td>
      <td class="weight-value ${ratioColor.text}">${formatValue(ratio, 2)}</td>
      <td class="dev-cell"><div class="dev-wrap">${deviationBar(deviation)}<span class="dev-label ${ratioColor.text}">${formatDeviation(deviation)}</span></div></td>
    </tr>`;
    if (isOpen) html += `<tr class="detail-placeholder" data-worker-id="${escapeHtml(workerId)}"></tr>`;
  });

  const totalRatio = totals.hours > 0 ? totals.weight / totals.hours : 0;
  html += `<tr class="totals-row">
    <td>${escapeHtml(t('Total'))}</td>
    <td class="weight-value">${formatValue(totals.hours, 2)}</td>
    <td class="weight-value">${formatValue(totals.balance, 2)}</td>
    <td class="weight-value">${totals.manual > 0 ? '+' : ''}${formatValue(totals.manual, 2)}</td>
    <td class="weight-value">${formatValue(totals.weight, 2)}</td>
    <td class="weight-value">${formatValue(totalRatio, 2)}</td>
    <td class="log-detail">${escapeHtml(t('Median weight / hour'))}: ${formatValue(benchmark, 2)}</td>
  </tr>`;
  tbody.innerHTML = html;

  const placeholder = tbody.querySelector('tr.detail-placeholder');
  if (placeholder) {
    if (preservedDetail && preservedDetail.dataset.workerId === placeholder.dataset.workerId) {
      placeholder.replaceWith(preservedDetail);
      refreshWorkerDetailData(preservedDetail);
    } else {
      placeholder.replaceWith(buildWorkerDetailRow(placeholder.dataset.workerId));
    }
  }
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

function getAssignmentStatus(item) {
  if (item.unresolved) return 'unresolved';
  if (item.overflowed) return 'overflow';
  return 'direct';
}

function buildLogEntries() {
  const entries = [];
  const worker = recentFilters.worker;
  if (recentFilters.type !== 'corrections') {
    recentData.forEach(function(item) {
      const workerName = String(item.person || '').toLowerCase();
      const workerRawName = String(item.person_raw || '').toLowerCase();
      if (worker && !workerName.includes(worker) && !workerRawName.includes(worker)) return;
      if (recentFilters.status && getAssignmentStatus(item) !== recentFilters.status) return;
      if (recentFilters.skill && item.requested_skill !== recentFilters.skill && item.actual_skill !== recentFilters.skill) return;
      if (recentFilters.modality && item.requested_modality !== recentFilters.modality && item.actual_modality !== recentFilters.modality) return;
      entries.push({ kind: 'assignment', timestamp: item.timestamp, item });
    });
  }
  const assignmentOnlyFilter = recentFilters.status || recentFilters.skill || recentFilters.modality;
  if (recentFilters.type !== 'assignments' && !assignmentOnlyFilter) {
    correctionLog.forEach(function(entry) {
      const name = String(entry.worker_name || entry.worker_id || '').toLowerCase();
      if (worker && !name.includes(worker)) return;
      entries.push({ kind: 'correction', timestamp: entry.timestamp, item: entry });
    });
  }
  entries.sort(function(a, b) { return String(b.timestamp || '').localeCompare(String(a.timestamp || '')); });
  return entries;
}

function renderLogRow(entry) {
  const item = entry.item;
  if (entry.kind === 'correction') {
    const delta = Number(item.delta || 0);
    const by = [item.admin_name, item.client_ip].filter(Boolean).join(' · ');
    return `<tr class="log-row--correction">
      <td>${escapeHtml(formatDateTime(item.timestamp))}</td>
      <td><span class="recent-pill recent-pill-correction">${escapeHtml(t('Correction'))}</span></td>
      <td>${escapeHtml(item.worker_name || item.worker_id || '-')}</td>
      <td>–</td>
      <td>–</td>
      <td class="log-detail">${escapeHtml(item.reason || '')}</td>
      <td class="num ${delta > 0 ? 'text-red' : 'text-green'}">${delta > 0 ? '+' : ''}${formatValue(delta, 2)}</td>
      <td class="log-detail">${escapeHtml(t('Total'))} ${formatValue(item.total_before, 2)} → ${formatValue(item.total_after, 2)}${by ? ` · ${escapeHtml(by)}` : ''}</td>
    </tr>`;
  }
  const requested = `${getSkillLabel(item.requested_skill)} / ${getModalityLabel(item.requested_modality)}`;
  const actual = `${getSkillLabel(item.actual_skill)} / ${getModalityLabel(item.actual_modality)}`;
  const status = getAssignmentStatus(item);
  const pill = {
    direct: '<span class="recent-pill recent-pill-ok">Direct</span>',
    overflow: '<span class="recent-pill recent-pill-overflow">Overflow</span>',
    unresolved: '<span class="recent-pill recent-pill-unresolved">Unresolved</span>',
  }[status];
  return `<tr>
    <td>${escapeHtml(formatDateTime(item.timestamp))}</td>
    <td>${escapeHtml(t('Assignment'))}</td>
    <td>${escapeHtml(item.person || '-')}</td>
    <td>${escapeHtml(requested)}</td>
    <td>${escapeHtml(actual)}</td>
    <td>${escapeHtml(item.task_label || '-')}</td>
    <td class="num">${formatValue(item.weight, 2)}</td>
    <td>${pill}</td>
  </tr>`;
}

function renderRecentTable() {
  const tbody = document.getElementById('tbody-recent');
  const summary = document.getElementById('recent-summary-note');
  if (!tbody) return;
  document.querySelectorAll('[data-log-type]').forEach(function(btn) {
    btn.setAttribute('aria-pressed', btn.dataset.logType === recentFilters.type ? 'true' : 'false');
  });
  const entries = buildLogEntries();
  const visibleItems = recentFilters.visible === 'full'
    ? entries
    : entries.slice(0, Math.max(parseInt(recentFilters.visible, 10) || 0, 0));
  if (summary) {
    summary.textContent = `${visibleItems.length} / ${entries.length} ${t('entries')} · ${recentData.length} ${t('assignments loaded')} · ${correctionLog.length} ${t('corrections today')}`;
  }
  if (!visibleItems.length) {
    tbody.innerHTML = `<tr><td colspan="8" class="no-data">${escapeHtml(t('No entries match the current filters.'))}</td></tr>`;
    return;
  }
  tbody.innerHTML = visibleItems.map(renderLogRow).join('');
}

function filterLogByType(type) {
  recentFilters.type = type || '';
  renderRecentTable();
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
  if (currentMode.startsWith('advanced')) lastMatrixMode = currentMode;
  MODES.forEach(function(modeName) {
    document.body.classList.remove(`mode-${modeName}`);
  });
  document.body.classList.add(`mode-${currentMode}`);
  const isMatrix = currentMode.startsWith('advanced');
  document.querySelectorAll('[data-mode]').forEach(function(btn) {
    const active = btn.dataset.mode === currentMode || (btn.dataset.mode === 'matrix' && isMatrix);
    btn.setAttribute('aria-pressed', active ? 'true' : 'false');
  });
  const view = getViewForMode(currentMode);
  document.querySelectorAll('[data-view]').forEach(function(tab) {
    tab.setAttribute('aria-selected', tab.dataset.view === view ? 'true' : 'false');
  });
  const url = new URL(window.location.href);
  url.searchParams.set('view', view);
  url.searchParams.delete('mode');
  window.history.replaceState(null, '', url);
  renderAllTables();
  if (skipLoad) {
    return;
  }
  if (currentMode === 'flow') {
    if (!flowDataLoaded) loadFlowData();
    window.RadimoDayOverview?.load();
  }
  if (currentMode === 'recent') {
    loadRecentData();
    loadCorrectionsData();
  }
}

function getViewForMode(mode) {
  if (mode === 'flow') return 'day';
  if (mode === 'recent') return 'log';
  return 'people';
}

let lastMatrixMode = 'advanced-weight';

function currentMatrixMode() {
  return lastMatrixMode;
}

function setView(view) {
  if (view === 'day') setMode('flow');
  else if (view === 'log') setMode('recent');
  else setMode(currentMode.startsWith('advanced') ? currentMode : 'simple');
}

function filterByModality(modality) {
  filters.modality = modality;
  document.querySelectorAll('.wl-filter-chips [data-modality]').forEach(function(btn) {
    btn.classList.toggle('is-active', btn.dataset.modality === modality);
  });
  renderAllTables();
}

function filterBySkill(skill) {
  filters.skill = skill;
  document.querySelectorAll('.wl-filter-chips [data-skill]').forEach(function(btn) {
    btn.classList.toggle('is-active', btn.dataset.skill === skill);
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
    lastUpdate.textContent = `${t('Updated')} ${new Date().toLocaleTimeString('de-DE')}`;
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
  return fetch('/api/performance/data')
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
  if (currentMode === 'flow' && window.RadimoDayOverview) {
    requests.push(window.RadimoDayOverview.load());
  }
  if (currentMode === 'recent' || expandedWorkerId) {
    requests.push(loadRecentData());
    requests.push(loadCorrectionsData());
  }
  return Promise.all(requests);
}

// =============================================================================
// Worker detail row: skill × modality breakdown, recent assignments, corrections
// =============================================================================

function loadCorrectionsData() {
  return fetch('/api/manual-adjustments')
    .then(function(response) { return response.json().then(function(payload) { return { response, payload }; }); })
    .then(function({ response, payload }) {
      if (!response.ok || !payload.success) throw new Error(payload.error || 'Failed to load corrections');
      correctionWorkers = payload.workers || [];
      correctionDeltas = payload.allowed_deltas || [];
      correctionLog = payload.adjustments || [];
      correctionsLoaded = true;
      if (currentMode === 'recent') renderRecentTable();
      document.querySelectorAll('#tbody-global tr.detail-row').forEach(refreshWorkerDetailData);
    })
    .catch(function(error) {
      console.error('Failed to load corrections:', error);
    });
}

function findWorker(workerId) {
  return workersData.find(function(worker) { return String(worker.canonical_id || worker.name) === workerId; });
}

function toggleWorkerDetail(workerId) {
  expandedWorkerId = expandedWorkerId === workerId ? null : workerId;
  renderGlobalTable();
  if (expandedWorkerId) {
    if (!recentDataLoaded) loadRecentData().then(function() { document.querySelectorAll('#tbody-global tr.detail-row').forEach(refreshWorkerDetailData); });
    if (!correctionsLoaded) loadCorrectionsData();
  }
}

function buildWorkerDetailRow(workerId) {
  const row = document.createElement('tr');
  row.className = 'detail-row';
  row.dataset.workerId = workerId;
  row.innerHTML = `<td colspan="7">
    <div class="worker-detail" onclick="event.stopPropagation()">
      <div class="worker-detail__box">
        <h4>${escapeHtml(t('Assignments by modality and skill'))}</h4>
        <div data-part="matrix"></div>
      </div>
      <div class="worker-detail__box">
        <h4>${escapeHtml(t('Recent assignments'))}</h4>
        <div class="mini-scroll" data-part="events"></div>
        <h4 style="margin-top:0.6rem">${escapeHtml(t('Corrections today'))}</h4>
        <div data-part="corrections"></div>
      </div>
      <div class="worker-detail__box">
        <h4>${escapeHtml(t('Book correction'))}</h4>
        <form class="correction-form" onsubmit="submitWorkerCorrection(event, this)">
          <label>${escapeHtml(t('Value'))}<select name="delta" onchange="updateCorrectionPreview(this.form)"></select></label>
          <label>${escapeHtml(t('Your name'))}<input name="admin_name" type="text" autocomplete="name" required></label>
          <label class="wide">${escapeHtml(t('Reason'))}<input name="reason" type="text" maxlength="160" required></label>
          <label class="wide">${escapeHtml(t('Admin password'))}<input name="admin_password" type="password" autocomplete="current-password" required></label>
          <div class="correction-preview" data-part="preview"></div>
          <div class="correction-actions">
            <button class="ui-btn" type="submit">${escapeHtml(t('Publish correction'))}</button>
            <span class="correction-status" data-part="status" aria-live="polite"></span>
          </div>
        </form>
        <p class="log-detail" style="margin-top:0.4rem">${escapeHtml(t('Corrections change weighted totals only; they create no assignment counts.'))}</p>
      </div>
    </div>
  </td>`;
  const form = row.querySelector('form');
  form.admin_name.value = localStorage.getItem('radimo.correction.adminName') || '';
  refreshWorkerDetailData(row);
  return row;
}

function refreshWorkerDetailData(row) {
  const worker = findWorker(row.dataset.workerId);
  if (!worker) return;
  const matrixEl = row.querySelector('[data-part="matrix"]');
  let matrix = `<table class="mini-table"><thead><tr><th></th>${MODALITIES.map(function(mod) { return `<th>${escapeHtml(getModalityLabel(mod))}</th>`; }).join('')}</tr></thead><tbody>`;
  SKILLS.forEach(function(skill) {
    matrix += `<tr><td>${escapeHtml(getSkillLabel(skill))}</td>`;
    MODALITIES.forEach(function(mod) {
      const count = getCellCount(worker, mod, skill);
      const weight = getCellDerivedWeight(worker, mod, skill);
      matrix += count
        ? `<td title="${escapeHtml(t('count × configured weight'))}">${count} · ${formatValue(weight, 2)}</td>`
        : '<td class="is-zero">–</td>';
    });
    matrix += '</tr>';
  });
  matrixEl.innerHTML = matrix + '</tbody></table>';

  const events = recentData.filter(function(item) { return String(item.canonical_id || '') === row.dataset.workerId; }).slice(0, 15);
  row.querySelector('[data-part="events"]').innerHTML = events.length
    ? `<table class="mini-table"><tbody>${events.map(function(item) {
        const status = getAssignmentStatus(item);
        return `<tr><td>${escapeHtml(formatDateTime(item.timestamp).split(', ').pop())}</td>
          <td>${escapeHtml(getSkillLabel(item.requested_skill))} / ${escapeHtml(getModalityLabel(item.requested_modality))}</td>
          <td>${status === 'direct' ? '' : `<span class="recent-pill recent-pill-${status === 'overflow' ? 'overflow' : 'unresolved'}">${escapeHtml(status === 'overflow' ? 'Overflow' : 'Unresolved')}</span>`}</td>
          <td>${formatValue(item.weight, 2)}</td></tr>`;
      }).join('')}</tbody></table>`
    : `<div class="log-detail">${escapeHtml(recentDataLoaded ? t('No assignments recorded today.') : t('Loading...'))}</div>`;

  const corrections = correctionLog.filter(function(entry) { return entry.worker_id === row.dataset.workerId; });
  row.querySelector('[data-part="corrections"]').innerHTML = corrections.length
    ? `<table class="mini-table"><tbody>${corrections.map(function(entry) {
        const delta = Number(entry.delta || 0);
        return `<tr><td>${escapeHtml(formatDateTime(entry.timestamp).split(', ').pop())}</td><td class="${delta > 0 ? 'text-red' : 'text-green'}">${delta > 0 ? '+' : ''}${formatValue(delta, 2)}</td><td style="text-align:left">${escapeHtml(entry.reason || '')}</td><td>${escapeHtml(entry.admin_name || '')}</td></tr>`;
      }).join('')}</tbody></table>`
    : `<div class="log-detail">${escapeHtml(t('None'))}</div>`;

  const select = row.querySelector('select[name="delta"]');
  if (select && correctionDeltas.length && !select.options.length) {
    const deltas = Array.from(new Set(correctionDeltas.map(Number).filter(Number.isFinite))).sort(function(a, b) { return a - b; });
    select.innerHTML = deltas.map(function(delta) {
      return `<option value="${delta}">${delta > 0 ? '+' : ''}${delta.toFixed(2)}</option>`;
    }).join('');
    if (deltas.includes(1)) select.value = '1';
  }
  updateCorrectionPreview(row.querySelector('form'));
}

function updateCorrectionPreview(form) {
  if (!form) return;
  const row = form.closest('tr.detail-row');
  const worker = findWorker(row.dataset.workerId);
  const preview = row.querySelector('[data-part="preview"]');
  const delta = Number(form.delta.value);
  if (!worker || !Number.isFinite(delta) || form.delta.value === '') {
    preview.textContent = t('Loading...');
    return;
  }
  const total = Number(worker.global_weight || 0);
  const hours = Number(worker.hours_worked_now || 0);
  const after = total + delta;
  const perHourBefore = hours > 0 ? total / hours : 0;
  const perHourAfter = hours > 0 ? after / hours : 0;
  preview.textContent = `${t('Total')} ${formatValue(total, 2)} → ${formatValue(after, 2)} · ${t('Weight / Hour')} ${formatValue(perHourBefore, 2)} → ${formatValue(perHourAfter, 2)}`;
}

function submitWorkerCorrection(event, form) {
  event.preventDefault();
  const row = form.closest('tr.detail-row');
  const status = row.querySelector('[data-part="status"]');
  const button = form.querySelector('button[type="submit"]');
  const payload = {
    worker_id: row.dataset.workerId,
    delta: Number(form.delta.value),
    admin_name: form.admin_name.value.trim(),
    reason: form.reason.value.trim(),
    admin_password: form.admin_password.value,
  };
  if (!payload.reason || !payload.admin_name || !payload.admin_password) {
    status.className = 'correction-status is-error';
    status.textContent = t('Please complete all required fields.');
    return;
  }
  button.disabled = true;
  status.className = 'correction-status';
  status.textContent = t('Publishing...');
  fetch('/api/manual-adjustments', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
    .then(function(response) { return response.json().then(function(result) { return { response, result }; }); })
    .then(function({ response, result }) {
      if (!response.ok || !result.success) throw new Error(result.error || 'Manual adjustment failed');
      localStorage.setItem('radimo.correction.adminName', payload.admin_name);
      correctionWorkers = result.workers || correctionWorkers;
      correctionLog = result.adjustments || correctionLog;
      form.reason.value = '';
      form.admin_password.value = '';
      status.className = 'correction-status is-success';
      const entry = result.entry || {};
      status.textContent = `${t('Published')}: ${t('Total')} ${formatValue(entry.total_before, 2)} → ${formatValue(entry.total_after, 2)}`;
      return loadData();
    })
    .catch(function(error) {
      status.className = 'correction-status is-error';
      status.textContent = error.message;
      form.admin_password.focus();
    })
    .finally(function() {
      button.disabled = false;
    });
}

document.addEventListener('DOMContentLoaded', function() {
  const params = new URLSearchParams(window.location.search);
  const view = params.get('view');
  if (view === 'day') currentMode = 'flow';
  else if (view === 'log') currentMode = 'recent';
  else if (view === 'people' && !currentMode.startsWith('advanced')) currentMode = 'simple';
  setMode(currentMode, { skipLoad: true });
  if (currentMode === 'flow') window.RadimoDayOverview?.load();
  if (currentMode === 'recent') loadCorrectionsData();
  toggleAutoRefresh();
});
