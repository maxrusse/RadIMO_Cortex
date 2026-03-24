// Worker Load Monitor JavaScript

// Parse config from JSON block
const CONFIG = JSON.parse(document.getElementById('page-config').textContent);
const SKILLS = CONFIG.skills;
const MODALITIES = CONFIG.modalities;
const SKILL_SETTINGS = CONFIG.skill_settings;
const MODALITY_SETTINGS = CONFIG.modality_settings;
const LOAD_MONITOR_CONFIG = CONFIG.load_monitor_config;
const UI_COLORS = CONFIG.ui_colors;
const WORKER_SORT_TITLES = new Set(['dr', 'pd', 'prof', 'med', 'dent', 'dipl', 'ing', 'dipl-ing']);
const WORKER_SORT_PARTICLES = new Set(['von', 'van', 'de', 'del', 'der', 'den', 'zu', 'zum', 'zur']);

// State
let currentMode = CONFIG.initial_mode || LOAD_MONITOR_CONFIG.default_view || 'simple';
let colorMode = LOAD_MONITOR_CONFIG.color_thresholds?.mode || 'absolute';
let workersData = [];
let maxWeight = 0;
let autoRefreshInterval = null;
let flowDataLoaded = false;
let flowData = null;
let modalityWeightData = {};
let skillWeightData = {};
let filters = { modality: '', skill: '', hideZero: false };
let sortState = {
  global: { column: 'weight', direction: 'desc' },
  modality: { column: 'total', direction: 'desc' },
  skill: { column: 'total', direction: 'desc' },
  advanced: { column: 'weight', direction: 'desc' }
};

// Generate dynamic CSS for modality colors
(function() {
  const style = document.createElement('style');
  let css = '';
  for (const [mod, settings] of Object.entries(MODALITY_SETTINGS)) {
    const navColor = settings.nav_color || '#6c757d';
    css += `.badge-${mod} { background: ${navColor}; }\n`;
    css += `.mod-header-${mod} { background: ${navColor}; color: white; }\n`;
  }
  for (const [skill, settings] of Object.entries(SKILL_SETTINGS)) {
    const btnColor = settings.button_color || '#6c757d';
    const textColor = settings.text_color || '#ffffff';
    css += `.skill-header-${skill.toLowerCase().replace(/[^a-z0-9]/g, '-')} { background: ${btnColor}; color: ${textColor}; }\n`;
  }
  style.textContent = css;
  document.head.appendChild(style);
})();

// Color calculation based on weight thresholds
function getLoadThresholds() {
  const thresholds = LOAD_MONITOR_CONFIG.color_thresholds || {};
  let lowThreshold, highThreshold;

  if (colorMode === 'relative' && maxWeight > 0) {
    const relConfig = thresholds.relative || { low_pct: 33, high_pct: 66 };
    lowThreshold = maxWeight * (relConfig.low_pct / 100);
    highThreshold = maxWeight * (relConfig.high_pct / 100);
  } else {
    const absConfig = thresholds.absolute || { low: 3.0, high: 7.0 };
    lowThreshold = absConfig.low;
    highThreshold = absConfig.high;
  }

  return { lowThreshold, highThreshold };
}

function getLoadColor(weight) {
  const { lowThreshold, highThreshold } = getLoadThresholds();

  if (weight <= 0) return { bg: '#e9ecef', text: 'text-muted' };
  if (weight < lowThreshold) return { bg: 'var(--load-green)', text: 'text-green' };
  if (weight < highThreshold) return { bg: 'var(--load-yellow)', text: 'text-yellow' };
  return { bg: 'var(--load-red)', text: 'text-red' };
}

function getLoadColorClass(weight) {
  const { lowThreshold, highThreshold } = getLoadThresholds();

  if (weight <= 0) return '';
  if (weight < lowThreshold) return 'load-green';
  if (weight < highThreshold) return 'load-yellow';
  return 'load-red';
}

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

// Mode switching
function setMode(mode) {
  currentMode = mode;
  document.body.classList.remove('mode-simple', 'mode-advanced', 'mode-flow');
  document.body.classList.add(`mode-${mode}`);

  document.querySelectorAll('.mode-btn').forEach(function(btn) {
    btn.classList.toggle('active', btn.dataset.mode === mode);
  });

  if (mode === 'flow') {
    if (!flowDataLoaded) {
      loadFlowData();
    } else {
      renderFlowDataState(flowData);
    }
    return;
  }

  renderAllTables();
}

// Color mode switching
function setColorMode(mode) {
  colorMode = mode;
  document.querySelectorAll('.color-btn').forEach(function(btn) {
    btn.classList.toggle('active', btn.dataset.color === mode);
  });
  renderAllTables();
}

// Filtering (Advanced mode)
function filterByModality(mod) {
  filters.modality = mod;
  document.querySelectorAll('[data-modality]').forEach(function(btn) {
    btn.classList.toggle('active', btn.dataset.modality === mod);
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

// Sorting
function sortTable(tableType, column) {
  const state = sortState[tableType];
  if (state.column === column) {
    state.direction = state.direction === 'asc' ? 'desc' : 'asc';
  } else {
    state.column = column;
    state.direction = column === 'name' ? 'asc' : 'desc';
  }

  renderAllTables();
}

function getSortValue(worker, column, tableType) {
  if (column === 'name') return buildWorkerSortKey(worker.name);
  if (column === 'weight') return worker.global_weight || 0;
  if (column === 'total') {
    if (tableType === 'modality') {
      return MODALITIES.reduce(function(total, mod) {
        return total + (worker.modalities[mod]?.assignment_total || 0);
      }, 0);
    }
    if (tableType === 'skill') {
      return SKILLS.reduce(function(total, skill) {
        return total + (worker.skills[skill] || 0);
      }, 0);
    }
    return worker.global_weight || 0;
  }
  if (MODALITIES.includes(column)) return worker.modalities[column]?.assignment_total || 0;
  if (SKILLS.includes(column)) return worker.skills[column] || 0;
  return 0;
}

function sortWorkers(workers, tableType) {
  const { column, direction } = sortState[tableType];
  const sorted = [...workers];
  const ascending = direction === 'asc';

  sorted.sort(function(a, b) {
    const valA = getSortValue(a, column, tableType);
    const valB = getSortValue(b, column, tableType);

    if (typeof valA === 'string') {
      return ascending ? valA.localeCompare(valB) : valB.localeCompare(valA);
    }
    return ascending ? valA - valB : valB - valA;
  });

  return sorted;
}

// Filter workers based on current filters
function filterWorkers(workers) {
  return workers.filter(function(worker) {
    // Hide zero filter
    if (filters.hideZero && worker.global_weight <= 0) {
      return false;
    }

    // Modality filter
    if (filters.modality && !worker.modalities[filters.modality]) {
      return false;
    }

    // Skill filter (worker must have assignment in that skill)
    if (filters.skill && (worker.skills[filters.skill] || 0) <= 0) {
      return false;
    }

    return true;
  });
}

// Render Global table (Simple mode)
function renderGlobalTable() {
  const tbody = document.getElementById('tbody-global');
  if (!tbody) return;

  const filteredWorkers = filterWorkers(workersData);
  const sorted = sortWorkers(filteredWorkers, 'global');

  if (sorted.length === 0) {
    tbody.innerHTML = '<tr><td colspan="3" class="no-data">No workers match filters</td></tr>';
    return;
  }

  const maxBarWeight = Math.max(maxWeight, 1);
  let html = '';

  let totalWeight = 0;

  sorted.forEach(function(worker) {
    const weight = worker.global_weight || 0;
    totalWeight += weight;
    const color = getLoadColor(weight);
    const colorClass = getLoadColorClass(weight);
    const barWidth = Math.min((weight / maxBarWeight) * 100, 100);

    html += `<tr>
      <td class="worker-col">${escapeHtml(worker.name)}</td>
      <td class="weight-value ${color.text}">${weight.toFixed(1)}</td>
      <td>
        <div class="weight-bar">
          <div class="weight-bar-fill ${colorClass}" style="width: ${barWidth}%; max-width: 200px;"></div>
        </div>
      </td>
    </tr>`;
  });

  // Add totals row
  const totalBarWidth = Math.min((totalWeight / maxBarWeight) * 100, 100);
  html += `<tr class="totals-row">
    <td class="worker-col" style="font-weight: 700;">Total</td>
    <td class="weight-value" style="font-weight: 700;">${totalWeight.toFixed(1)}</td>
    <td>
      <div class="weight-bar">
        <div class="weight-bar-fill" style="width: ${totalBarWidth}%; max-width: 200px; background: #6c757d;"></div>
      </div>
    </td>
  </tr>`;

  tbody.innerHTML = html;
}

// Render Per-Modality table (Simple mode)
function renderModalityTable() {
  const container = document.getElementById('summary-modality');
  if (!container) return;

  const filteredWorkers = filterWorkers(workersData);
  const visibleWorkerIds = new Set(filteredWorkers.map(function(worker) {
    return worker.canonical_id;
  }));
  const grandWeight = MODALITIES.reduce(function(total, mod) {
    const weighted = modalityWeightData[mod] || {};
    return total + Object.entries(weighted).reduce(function(modTotal, [canonicalId, value]) {
      return modTotal + (visibleWorkerIds.has(canonicalId) ? Number(value || 0) : 0);
    }, 0);
  }, 0);

  const cards = MODALITIES.map(function(mod) {
    const settings = MODALITY_SETTINGS[mod] || {};
    const label = settings.label || mod.toUpperCase();
    const color = settings.nav_color || '#6c757d';
    const assignments = filteredWorkers.reduce(function(sum, worker) {
      return sum + (worker.modalities[mod]?.assignment_total || 0);
    }, 0);
    const weight = filteredWorkers.reduce(function(sum, worker) {
      return sum + Number(worker.modalities[mod]?.weighted_total || 0);
    }, 0);
    const activeWorkers = filteredWorkers.reduce(function(sum, worker) {
      return sum + ((worker.modalities[mod]?.assignment_total || 0) > 0 ? 1 : 0);
    }, 0);
    const share = grandWeight > 0 ? Math.round((weight / grandWeight) * 100) : 0;

    return {
      label,
      color,
      assignments,
      weight,
      activeWorkers,
      share
    };
  });

  if (!cards.some(function(card) { return card.assignments > 0 || card.weight > 0 || card.activeWorkers > 0; })) {
    container.innerHTML = '<div class="summary-card-empty">No modality activity for the current filter.</div>';
    return;
  }

  container.innerHTML = cards.map(function(card) {
    return `<div class="summary-card">
      <div class="summary-card-header">
        <span class="summary-card-title">${escapeHtml(card.label)}</span>
        <span class="summary-card-badge" style="background:${card.color};">${card.share}%</span>
      </div>
      <div class="summary-card-main">${card.weight.toFixed(1)}</div>
      <div class="summary-card-main-label">Weighted</div>
      <div class="summary-card-sub summary-card-sub-stack">
        <span>Assignments</span>
        <span>${card.assignments}</span>
      </div>
      <div class="summary-card-sub">
        <span>${card.activeWorkers} active</span>
        <span>${card.assignments > 0 ? 'live' : 'idle'}</span>
      </div>
    </div>`;
  }).join('');
}

// Render Per-Skill table (Simple mode)
function renderSkillTable() {
  const container = document.getElementById('summary-skill');
  if (!container) return;

  const filteredWorkers = filterWorkers(workersData);
  const visibleWorkerIds = new Set(filteredWorkers.map(function(worker) {
    return worker.canonical_id;
  }));
  const grandWeight = SKILLS.reduce(function(total, skill) {
    const weighted = skillWeightData[skill] || {};
    return total + Object.entries(weighted).reduce(function(skillTotal, [canonicalId, value]) {
      return skillTotal + (visibleWorkerIds.has(canonicalId) ? Number(value || 0) : 0);
    }, 0);
  }, 0);

  const cards = SKILLS.map(function(skill) {
    const settings = SKILL_SETTINGS[skill] || {};
    const label = settings.label || skill;
    const color = settings.button_color || '#6c757d';
    const assignments = filteredWorkers.reduce(function(sum, worker) {
      return sum + (worker.skills[skill] || 0);
    }, 0);
    const weight = filteredWorkers.reduce(function(sum, worker) {
      return sum + Number(worker.skill_weights?.[skill] || 0);
    }, 0);
    const activeWorkers = filteredWorkers.reduce(function(sum, worker) {
      return sum + ((worker.skills[skill] || 0) > 0 ? 1 : 0);
    }, 0);
    const share = grandWeight > 0 ? Math.round((weight / grandWeight) * 100) : 0;

    return {
      label,
      color,
      assignments,
      weight,
      activeWorkers,
      share
    };
  });

  if (!cards.some(function(card) { return card.assignments > 0 || card.weight > 0 || card.activeWorkers > 0; })) {
    container.innerHTML = '<div class="summary-card-empty">No skill activity for the current filter.</div>';
    return;
  }

  container.innerHTML = cards.map(function(card) {
    return `<div class="summary-card">
      <div class="summary-card-header">
        <span class="summary-card-title">${escapeHtml(card.label)}</span>
        <span class="summary-card-badge" style="background:${card.color};">${card.share}%</span>
      </div>
      <div class="summary-card-main">${card.weight.toFixed(1)}</div>
      <div class="summary-card-main-label">Weighted</div>
      <div class="summary-card-sub summary-card-sub-stack">
        <span>Assignments</span>
        <span>${card.assignments}</span>
      </div>
      <div class="summary-card-sub">
        <span>${card.activeWorkers} active</span>
        <span>${card.assignments > 0 ? 'live' : 'idle'}</span>
      </div>
    </div>`;
  }).join('');
}

// Render Advanced table (Full matrix)
function renderAdvancedTable() {
  const thead = document.getElementById('thead-advanced');
  const tbody = document.getElementById('tbody-advanced');
  if (!thead || !tbody) return;

  const filteredWorkers = filterWorkers(workersData);
  const sorted = sortWorkers(filteredWorkers, 'advanced');

  // Determine which modalities/skills to show based on filters
  const showModalities = filters.modality ? [filters.modality] : MODALITIES;
  const showSkills = filters.skill ? [filters.skill] : SKILLS;

  // Build header
  let headerTop = '<tr class="header-top"><th rowspan="2" class="sortable worker-col" data-sort="name" onclick="sortTable(\'advanced\', \'name\')">Worker</th>';
  let headerSub = '<tr class="header-sub">';

  showModalities.forEach(function(mod) {
    const modSettings = MODALITY_SETTINGS[mod] || {};
    const label = modSettings.label || mod.toUpperCase();
    const colSpan = showSkills.length;
    headerTop += `<th colspan="${colSpan}" class="mod-header-${mod}">${label}</th>`;

    showSkills.forEach(function(skill) {
      const skillSettings = SKILL_SETTINGS[skill] || {};
      const skillLabel = skillSettings.label || skill;
      const skillClass = `skill-header-${skill.toLowerCase().replace(/[^a-z0-9]/g, '-')}`;
      headerSub += `<th class="${skillClass}" title="${skillLabel}">${skillLabel}</th>`;
    });
  });

  headerTop += '<th rowspan="2" class="sortable" data-sort="weight" onclick="sortTable(\'advanced\', \'weight\')">Total</th></tr>';
  headerSub += '</tr>';

  thead.innerHTML = headerTop + headerSub;

  // Build body
  if (sorted.length === 0) {
    const colCount = showModalities.length * showSkills.length + 2;
    tbody.innerHTML = `<tr><td colspan="${colCount}" class="no-data">No workers match filters</td></tr>`;
    return;
  }

  let html = '';

  // Track column totals for each modality-skill combination
  const cellTotals = {};
  showModalities.forEach(function(mod) {
    cellTotals[mod] = {};
    showSkills.forEach(function(skill) {
      cellTotals[mod][skill] = 0;
    });
  });
  let grandTotal = 0;

  sorted.forEach(function(worker) {
    html += '<tr>';
    html += `<td class="worker-col">${escapeHtml(worker.name)}</td>`;

    showModalities.forEach(function(mod) {
      const modData = worker.modalities[mod];

      showSkills.forEach(function(skill) {
        const count = modData?.skill_counts?.[skill] || 0;
        cellTotals[mod][skill] += count;
        const color = getLoadColor(count);

        if (count > 0) {
          html += `<td class="${color.text}" style="font-weight: 600;">${count}</td>`;
        } else {
          html += '<td style="color: #ccc;">-</td>';
        }
      });
    });

    const workerWeight = worker.global_weight || 0;
    grandTotal += workerWeight;
    const totalColor = getLoadColor(workerWeight);
    html += `<td class="${totalColor.text}" style="font-weight: 700;">${workerWeight.toFixed(1)}</td>`;
    html += '</tr>';
  });

  // Add totals row
  html += '<tr class="totals-row">';
  html += '<td class="worker-col" style="font-weight: 700;">Total</td>';
  showModalities.forEach(function(mod) {
    showSkills.forEach(function(skill) {
      const count = cellTotals[mod][skill];
      html += `<td style="font-weight: 700;">${count > 0 ? count : '-'}</td>`;
    });
  });
  html += `<td style="font-weight: 700;">${grandTotal.toFixed(1)}</td>`;
  html += '</tr>';

  tbody.innerHTML = html;
}

function renderAllTables() {
  if (currentMode === 'flow') {
    if (flowDataLoaded) {
      renderFlowDataState(flowData);
    }
  } else if (currentMode === 'simple') {
    renderGlobalTable();
    renderModalityTable();
    renderSkillTable();
    updateSortIndicators('global');
  } else {
    renderAdvancedTable();
    updateSortIndicators('advanced');
  }

  // Show/hide no data message
  const noDataMsg = document.getElementById('no-data-msg');
  if (noDataMsg) {
    noDataMsg.style.display = currentMode !== 'flow' && workersData.length === 0 ? 'block' : 'none';
  }
}

function updateSortIndicators(tableType) {
  const state = sortState[tableType];
  const tableId = `table-${tableType}`;
  document.querySelectorAll(`#${tableId} th`).forEach(function(th) {
    th.classList.remove('sort-asc', 'sort-desc');
    if (th.dataset.sort === state.column) {
      th.classList.add(state.direction === 'asc' ? 'sort-asc' : 'sort-desc');
    }
  });
}

// Auto-refresh
function toggleAutoRefresh() {
  const checkbox = document.getElementById('auto-refresh');
  if (checkbox?.checked) {
    refreshCurrentMode();
    autoRefreshInterval = setInterval(refreshCurrentMode, 30000);
  } else {
    if (autoRefreshInterval) {
      clearInterval(autoRefreshInterval);
      autoRefreshInterval = null;
    }
  }
}

function refreshCurrentMode() {
  if (currentMode === 'flow') {
    return loadFlowData();
  }
  return loadData();
}

// Load data from API
function loadData() {
  return fetch('/api/worker-load/data')
    .then(function(response) {
      if (!response.ok) {
        throw new Error(`Failed to load worker data (${response.status})`);
      }
      return response.json();
    })
    .then(function(data) {
      if (data.success) {
        workersData = data.workers || [];
        modalityWeightData = data.modality_weights || {};
        skillWeightData = data.skill_weights || {};
        maxWeight = data.max_weight || 0;

        // Update last update time
        const lastUpdate = document.getElementById('last-update');
        if (lastUpdate) {
          lastUpdate.textContent = `Updated: ${new Date().toLocaleTimeString()}`;
        }

        renderAllTables();
      } else {
        console.error('Failed to load worker data:', data.error);
      }
    })
    .catch(function(error) {
      console.error('Error loading worker data:', error);
    });
}

// Escape HTML
function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text == null ? '' : String(text);
  return div.innerHTML;
}

function formatFlowValue(value) {
  const numeric = Number(value || 0);
  return numeric.toFixed(numeric % 1 === 0 ? 0 : 1);
}

function getSkillColor(skillKey) {
  return SKILL_SETTINGS[skillKey]?.button_color || '#5b7ea6';
}

function dataSkillLabel(skillKey) {
  return SKILL_SETTINGS[skillKey]?.label || skillKey;
}

function escapeAttribute(text) {
  return escapeHtml(text).replace(/"/g, '&quot;');
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
  const groupGap = 20;
  const topPadding = 42;
  const bottomPadding = 24;

  function layoutSide(skillList, totalKey) {
    const skillOrder = SKILLS.filter(function(skill) { return skillList.includes(skill); });
    skillList.forEach(function(skill) {
      if (!skillOrder.includes(skill)) skillOrder.push(skill);
    });
    let cursorY = topPadding;
    const positioned = [];

    skillOrder.forEach(function(skill) {
      const totals = data.totals?.[skill] || {};
      const total = Number(totals[totalKey] || 0);
      if (total <= 0) {
        return;
      }
      positioned.push({
        skill: skill,
        y: cursorY,
        centerY: cursorY + (rowHeight / 2),
        total: total,
        color: getSkillColor(skill),
        label: dataSkillLabel(skill)
      });
      cursorY += rowHeight + rowGap;
    });

    return {
      nodes: positioned,
      height: cursorY - rowGap + bottomPadding
    };
  }

  const leftLayout = layoutSide(activeSkills, 'out_total');
  const rightLayout = layoutSide(activeSkills, 'in_total');
  const height = Math.max(leftLayout.height, rightLayout.height, 220);

  const leftPos = {};
  leftLayout.nodes.forEach(function(node) { leftPos[node.skill] = node; });
  const rightPos = {};
  rightLayout.nodes.forEach(function(node) { rightPos[node.skill] = node; });

  const maxWeight = Math.max.apply(null, links.map(function(link) { return Number(link.weight || 0); }));
  const scaleWidth = function(weight) {
    return 2 + ((weight / Math.max(maxWeight, 1)) * 14);
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
    <text x="${rightX + nodeWidth}" y="22" font-size="13" font-weight="700" text-anchor="end" fill="#004892">Absorbing Main Skill</text>
    ${linkSvg}
    ${renderNodes(leftLayout.nodes, leftX, 'left')}
    ${renderNodes(rightLayout.nodes, rightX, 'right')}
  `;
}

function updateFlowMeta(data) {
  const windowEl = document.getElementById('meta-window');
  const resetEl = document.getElementById('meta-reset-date');
  const totalEl = document.getElementById('meta-total');
  const lastUpdate = document.getElementById('last-update');

  if (windowEl) {
    windowEl.textContent = data.meta && data.meta.window ? data.meta.window : '-';
  }
  if (resetEl) {
    resetEl.textContent = data.meta && data.meta.last_reset_date ? data.meta.last_reset_date : '-';
  }
  if (totalEl) {
    totalEl.textContent = formatFlowValue(data.grand_totals?.cross_pool_total || 0);
  }
  if (lastUpdate) {
    lastUpdate.textContent = `Updated: ${new Date().toLocaleTimeString()}`;
  }
}

function renderFlowDataState(data) {
  if (!data) {
    return;
  }

  updateFlowMeta(data);
  renderFlowDiagram(data);
  const noDataMsg = document.getElementById('flow-no-data-msg');
  if (noDataMsg) {
    const links = getFlowLinks(data);
    noDataMsg.style.display = links.length ? 'none' : 'block';
  }
}

function loadFlowData() {
  return fetch('/api/flow-balance/data')
    .then(function(response) {
      if (!response.ok) {
        throw new Error(`Flow data request failed (${response.status})`);
      }
      return response.json();
    })
    .then(function(data) {
      flowData = data;
      flowDataLoaded = true;
      renderFlowDataState(data);
    })
    .catch(function(error) {
      console.error('Failed to load flow data:', error);
    });
}

// Initialize
document.addEventListener('DOMContentLoaded', function() {
  setColorMode(colorMode);
  setMode(currentMode);
  if (currentMode !== 'flow') {
    refreshCurrentMode();
  }
});
