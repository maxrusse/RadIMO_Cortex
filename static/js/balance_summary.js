const CONFIG = JSON.parse(document.getElementById('page-config').textContent);
const SKILLS = CONFIG.skills || [];
const MODALITIES = CONFIG.modalities || [];
const SKILL_SETTINGS = CONFIG.skill_settings || {};
const MODALITY_SETTINGS = CONFIG.modality_settings || {};
let summaryAutoRefreshInterval = null;

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

function getRequestedSkillOverflowMetrics(flowPayload) {
  const bySkill = flowPayload.summary?.by_requested_skill || {};
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
  });
}

function classifyPerformanceStatus(flowPayload, options = {}) {
  const workerDataAvailable = options.workerDataAvailable !== false;
  const flowDataAvailable = options.flowDataAvailable !== false;
  if (!workerDataAvailable || !flowDataAvailable) {
    return { label: 'Partial', color: '#6c757d', note: 'Showing partial data while one source is unavailable' };
  }
  const hasWorkerData = Number(flowPayload.worker_count || 0) > 0;
  const overflowQuote = Number(flowPayload.summary?.overflow_quote || 0);
  const totalInflow = Number(flowPayload.summary?.total_inflow_weight || 0);
  if (!hasWorkerData && totalInflow <= 0) {
    return { label: 'No Data', color: '#6c757d', note: 'No worker or inflow data recorded yet' };
  }
  if (overflowQuote >= 0.35) {
    return { label: 'Strained', color: '#b02a37', note: "Overflow is carrying a large share of today's load" };
  }
  if (overflowQuote >= 0.2) {
    return { label: 'Watch', color: '#856404', note: "Overflow is materially supporting today's balance" };
  }
  return { label: 'Stable', color: '#2d7a46', note: 'Most load is still absorbed directly' };
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
    return {
      key: skill,
      label: getSkillLabel(skill),
      color: getSkillColor(skill),
      weightTotal,
      hoursTotal,
      weightPerHour: hoursTotal > 0 ? weightTotal / hoursTotal : 0,
    };
  }).sort(function(a, b) {
    return b.weightPerHour - a.weightPerHour;
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
    return {
      key: modality,
      label: getModalityLabel(modality),
      color: getModalityColor(modality),
      weightTotal,
      hoursTotal,
      weightPerHour: hoursTotal > 0 ? weightTotal / hoursTotal : 0,
    };
  }).sort(function(a, b) {
    return b.weightPerHour - a.weightPerHour;
  });
}

function renderOverviewCards(workerPayload, flowPayload, options = {}) {
  const primaryContainer = document.getElementById('summary-overview');
  if (!primaryContainer) return;

  const workers = workerPayload.workers || [];
  const totalWeight = workers.reduce(function(sum, worker) { return sum + Number(worker.global_weight || 0); }, 0);
  const totalHours = workers.reduce(function(sum, worker) { return sum + Number(worker.hours_worked_now || 0); }, 0);
  const globalPerHour = totalHours > 0 ? totalWeight / totalHours : 0;
  const overflowSummary = flowPayload.summary || {};
  const requestInflow = Number(overflowSummary.total_inflow_weight || 0);
  const recordedWorkers = workers.length;
  const status = classifyPerformanceStatus(
    {
      ...flowPayload,
      worker_count: recordedWorkers,
    },
    options,
  );

  const primaryCards = [
    {
      title: 'Global Load / Hour',
      badge: status.label,
      color: status.color,
      main: formatValue(globalPerHour, 2),
      className: 'summary-card-primary',
      rows: [
        { left: 'Status', right: status.note },
        { left: 'Total weight', right: formatValue(totalWeight) },
        { left: 'Total hours', right: formatValue(totalHours) },
      ],
    },
    {
      title: 'Total Load So Far',
      badge: `${recordedWorkers} workers`,
      color: '#4d647e',
      main: formatValue(totalWeight, 1),
      className: 'summary-card-primary',
      rows: [
        { left: 'Request inflow', right: formatValue(requestInflow, 1) },
        { left: 'Global load / hour', right: formatValue(globalPerHour, 2) },
      ],
    },
  ];

  function renderCards(cards) {
    return cards.map(function(card) {
      const cardClass = card.className ? `summary-card ${card.className}` : 'summary-card';
      return `<div class="${cardClass}">
      <div class="summary-card-header">
        <span class="summary-card-title">${escapeHtml(card.title)}</span>
        <span class="summary-card-badge" style="background:${card.color};">${escapeHtml(card.badge)}</span>
      </div>
      <div class="summary-card-main">${escapeHtml(card.main)}</div>
      ${card.rows.map(function(row) {
        return `<div class="summary-card-sub"><span>${escapeHtml(row.left)}</span><span>${escapeHtml(row.right)}</span></div>`;
      }).join('')}
    </div>`;
    }).join('');
  }

  primaryContainer.innerHTML = renderCards(primaryCards);
}

function renderLeaderList(id, items, formatter) {
  const target = document.getElementById(id);
  if (!target) return;
  if (!items.length) {
    target.innerHTML = '<li>No data yet.</li>';
    return;
  }
  target.innerHTML = items.map(function(item) {
    return `<li>${formatter(item)}</li>`;
  }).join('');
}

function renderLeaderSections(workerPayload, flowPayload) {
  const workers = workerPayload.workers || [];
  const skills = computeSkillMetrics(workers);
  const modalities = computeModalityMetrics(workers);
  const topSkills = skills.slice(0, 5);
  const topModalities = modalities.slice(0, 5);
  const overflowSkills = getRequestedSkillOverflowMetrics(flowPayload)
    .filter(function(item) { return item.overflowWeight > 0; })
    .sort(function(a, b) {
      if (b.overflowQuote !== a.overflowQuote) return b.overflowQuote - a.overflowQuote;
      return b.overflowWeight - a.overflowWeight;
    })
    .slice(0, 5);
  const overflowLinks = (flowPayload.links || [])
    .filter(function(link) { return Number(link.weight || 0) > 0; })
    .sort(function(a, b) { return Number(b.weight || 0) - Number(a.weight || 0); })
    .slice(0, 5);

  renderLeaderList('leaders-skills', topSkills, function(item) {
    return `${escapeHtml(item.label)}: <strong>${formatValue(item.weightPerHour, 2)}</strong> /h`;
  });
  renderLeaderList('leaders-modalities', topModalities, function(item) {
    return `${escapeHtml(item.label)}: <strong>${formatValue(item.weightPerHour, 2)}</strong> /h`;
  });
  renderLeaderList('leaders-skill-total', skills.sort(function(a, b) {
    return b.weightTotal - a.weightTotal;
  }), function(item) {
    return `${escapeHtml(item.label)}: <strong>${formatValue(item.weightTotal, 1)}</strong> total <span style="color:#667;">(${formatValue(item.weightPerHour, 2)} /h)</span>`;
  });
  renderLeaderList('leaders-modality-total', modalities.sort(function(a, b) {
    return b.weightTotal - a.weightTotal;
  }), function(item) {
    return `${escapeHtml(item.label)}: <strong>${formatValue(item.weightTotal, 1)}</strong> total <span style="color:#667;">(${formatValue(item.weightPerHour, 2)} /h)</span>`;
  });
  renderLeaderList('leaders-overflow-skills', overflowSkills, function(item) {
    return `${escapeHtml(item.label)}: <strong>${formatPercent(item.overflowQuote)}</strong> (${formatValue(item.overflowWeight, 1)} / ${formatValue(item.inflowWeight, 1)})`;
  });
  renderLeaderList('leaders-overflow', overflowLinks, function(item) {
    const from = flowPayload.skill_labels?.[item.from] || item.from;
    const to = flowPayload.skill_labels?.[item.to] || item.to;
    return `${escapeHtml(from)} → ${escapeHtml(to)}: <strong>${formatValue(item.weight, 1)}</strong>`;
  });
}

function loadSummaryData() {
  return Promise.allSettled([
    fetch('/api/worker-load/data').then(function(response) {
      if (!response.ok) throw new Error(`Worker load request failed (${response.status})`);
      return response.json();
    }),
    fetch('/api/flow-balance/data').then(function(response) {
      if (!response.ok) throw new Error(`Flow request failed (${response.status})`);
      return response.json();
    }),
  ]).then(function(results) {
    const workerPayload = results[0].status === 'fulfilled' ? results[0].value : { workers: [], summary: {} };
    const flowPayload = results[1].status === 'fulfilled' ? results[1].value : { links: [], summary: {}, skill_labels: {} };
    renderOverviewCards(workerPayload, flowPayload, {
      workerDataAvailable: results[0].status === 'fulfilled',
      flowDataAvailable: results[1].status === 'fulfilled',
    });
    renderLeaderSections(workerPayload, flowPayload);
    if (results.every(function(result) { return result.status !== 'fulfilled'; })) {
      throw new Error('Failed to load summary data.');
    }
  }).catch(function(error) {
    console.error('Failed to load summary data:', error);
    const container = document.getElementById('summary-overview');
    if (container) {
      container.innerHTML = `<div class="summary-card-empty">${escapeHtml(error.message || 'Failed to load summary data.')}</div>`;
    }
  });
}

document.addEventListener('DOMContentLoaded', function() {
  loadSummaryData();
  if (summaryAutoRefreshInterval) {
    clearInterval(summaryAutoRefreshInterval);
  }
  summaryAutoRefreshInterval = setInterval(loadSummaryData, 30000);
});
