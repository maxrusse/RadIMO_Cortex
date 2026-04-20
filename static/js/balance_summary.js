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

function formatMaybeValue(value, digits = 1) {
  if (value == null || Number.isNaN(Number(value))) return '—';
  return Number(value).toFixed(digits);
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

function getRequestedSkillOverflowMetrics(flowPayload) {
  const bySkill = flowPayload.summary?.by_requested_skill || {};
  return Object.entries(bySkill).map(function([skill, metrics]) {
    return {
      key: skill,
      label: getSkillLabel(skill),
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
  const workerDataAvailable = options.workerDataAvailable !== false;
  const flowDataAvailable = options.flowDataAvailable !== false;
  const totalWeight = workerDataAvailable
    ? workers.reduce(function(sum, worker) { return sum + Number(worker.global_weight || 0); }, 0)
    : null;
  const totalHours = workerDataAvailable
    ? workers.reduce(function(sum, worker) { return sum + Number(worker.hours_worked_now || 0); }, 0)
    : null;
  const globalPerHour = workerDataAvailable && totalHours > 0 ? totalWeight / totalHours : (workerDataAvailable ? 0 : null);
  const overflowSummary = flowPayload.summary || {};
  const requestInflow = flowDataAvailable ? Number(overflowSummary.total_inflow_weight || 0) : null;
  const recordedWorkers = workerDataAvailable ? workers.length : null;
  const overflowSupport = flowDataAvailable ? Number(overflowSummary.overflow_weight_total || 0) : null;
  const dataState = !workerDataAvailable || !flowDataAvailable
    ? 'Partial data'
    : ((recordedWorkers > 0 || requestInflow > 0) ? 'Current day' : 'No data yet');

  const primaryCards = [
    {
      title: 'Day Load',
      kicker: dataState,
      main: formatMaybeValue(requestInflow, 1),
      className: 'summary-card-primary',
      rows: [
        { left: 'Absorbed load so far', right: formatMaybeValue(totalWeight, 1) },
        { left: 'Overflow support', right: formatMaybeValue(overflowSupport, 1) },
      ],
    },
    {
      title: 'Global Load / Hour',
      kicker: 'Till now',
      main: formatMaybeValue(globalPerHour, 2),
      className: 'summary-card-primary',
      rows: [
        { left: 'Worker hours', right: formatMaybeValue(totalHours, 1) },
        { left: 'Recorded workers', right: recordedWorkers == null ? '—' : String(recordedWorkers) },
      ],
    },
  ];

  function renderCards(cards) {
    return cards.map(function(card) {
      const cardClass = card.className ? `summary-card ${card.className}` : 'summary-card';
      return `<div class="${cardClass}">
      <div class="summary-card-header">
        <span class="summary-card-title">${escapeHtml(card.title)}</span>
        ${card.kicker ? `<div class="summary-card-kicker">${escapeHtml(card.kicker)}</div>` : ''}
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
    return `${escapeHtml(item.label)}: <strong>${formatValue(item.weightTotal, 1)}</strong> load <span style="color:#667;">(${formatValue(item.weightPerHour, 2)} /h)</span>`;
  });
  renderLeaderList('leaders-modality-total', modalities.sort(function(a, b) {
    return b.weightTotal - a.weightTotal;
  }), function(item) {
    return `${escapeHtml(item.label)}: <strong>${formatValue(item.weightTotal, 1)}</strong> load <span style="color:#667;">(${formatValue(item.weightPerHour, 2)} /h)</span>`;
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
