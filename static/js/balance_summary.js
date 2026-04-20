const CONFIG = JSON.parse(document.getElementById('page-config').textContent);
const SKILLS = CONFIG.skills || [];
const MODALITIES = CONFIG.modalities || [];
const SKILL_SETTINGS = CONFIG.skill_settings || {};
const MODALITY_SETTINGS = CONFIG.modality_settings || {};

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

function getValidWorkerThresholdHours(workerPayload) {
  return Number(workerPayload.summary?.valid_worker_threshold_hours || 1.0);
}

function computeBandStats(workerPayload) {
  const workers = workerPayload.workers || [];
  const threshold = getValidWorkerThresholdHours(workerPayload);
  const validWorkers = workers.filter(function(worker) {
    return Number(worker.hours_worked_now || 0) >= threshold;
  });
  const benchmark = validWorkers.length
    ? validWorkers.reduce(function(sum, worker) {
        return sum + Number(worker.weight_per_hour || 0);
      }, 0) / validWorkers.length
    : 0;
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
    overBandWorkers,
    underBandWorkers,
    inBandCount: Math.max(validWorkers.length - overBandWorkers.length - underBandWorkers.length, 0),
    threshold,
  };
}

function classifySystemStatus(bandStats, flowPayload) {
  const overflowQuote = Number(flowPayload.summary?.overflow_quote || 0);
  const unresolvedQuote = Number(flowPayload.summary?.unresolved_quote || 0);
  const validCount = bandStats.validWorkers.length || 1;
  const overBandShare = bandStats.overBandWorkers.length / validCount;
  const underBandShare = bandStats.underBandWorkers.length / validCount;

  if (!bandStats.validWorkers.length) {
    return { label: 'No Baseline', color: '#6c757d', note: 'No valid worker-hour baseline yet' };
  }
  if (overflowQuote >= 0.35 || overBandShare >= 0.4 || unresolvedQuote >= 0.2) {
    return { label: 'Strained', color: '#b02a37', note: 'High overflow or many workers above band' };
  }
  if (overflowQuote >= 0.2 || overBandShare >= 0.25 || underBandShare >= 0.35) {
    return { label: 'Watch', color: '#856404', note: 'Uneven load or meaningful overflow pressure' };
  }
  return { label: 'Stable', color: '#2d7a46', note: 'Most active workers inside the 20% band' };
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

function renderOverviewCards(workerPayload, flowPayload) {
  const primaryContainer = document.getElementById('summary-overview');
  const secondaryContainer = document.getElementById('summary-secondary');
  if (!primaryContainer) return;

  const workers = workerPayload.workers || [];
  const bandStats = computeBandStats(workerPayload);
  const status = classifySystemStatus(bandStats, flowPayload);
  const totalWeight = workers.reduce(function(sum, worker) { return sum + Number(worker.global_weight || 0); }, 0);
  const totalHours = workers.reduce(function(sum, worker) { return sum + Number(worker.hours_worked_now || 0); }, 0);
  const globalPerHour = totalHours > 0 ? totalWeight / totalHours : 0;
  const maxWorker = workerPayload.summary?.global?.max_worker_per_hour;
  const minWorker = workerPayload.summary?.global?.min_worker_per_hour;
  const overflowSkills = getRequestedSkillOverflowMetrics(flowPayload)
    .sort(function(a, b) {
      if (b.overflowQuote !== a.overflowQuote) return b.overflowQuote - a.overflowQuote;
      return b.overflowWeight - a.overflowWeight;
    });
  const overflowSummary = flowPayload.summary || {};

  const primaryCards = [
    {
      title: 'System Status',
      badge: status.label,
      color: status.color,
      main: status.note,
      className: 'summary-card-primary summary-card-status',
      rows: [
        { left: 'Valid baseline', right: `${bandStats.validWorkers.length} workers` },
        { left: 'Threshold', right: `${formatValue(bandStats.threshold, 1)} h` },
      ],
    },
    {
      title: 'Global Load / Hour',
      badge: `${bandStats.validWorkers.length} valid`,
      color: '#3b6ea5',
      main: formatValue(globalPerHour, 2),
      className: 'summary-card-primary',
      rows: [
        { left: 'Total weight', right: formatValue(totalWeight) },
        { left: 'Total hours', right: formatValue(totalHours) },
      ],
    },
    {
      title: 'Overflow Pressure',
      badge: formatPercent(overflowSummary.overflow_quote || 0),
      color: '#856404',
      main: formatValue(overflowSummary.overflow_weight_total || 0, 1),
      className: 'summary-card-primary',
      rows: [
        { left: 'Request inflow', right: formatValue(overflowSummary.total_inflow_weight || 0, 1) },
        { left: 'Assigned base', right: formatValue(overflowSummary.total_assigned_base_weight || 0, 1) },
      ],
    },
  ];

  const secondaryCards = [
    {
      title: 'Load Spread',
      badge: minWorker?.name || '-',
      color: '#6c757d',
      main: maxWorker && minWorker ? formatValue(Number(maxWorker.weight_per_hour || 0) - Number(minWorker.weight_per_hour || 0), 2) : '-',
      rows: [
        { left: 'Max / hour', right: maxWorker ? formatValue(maxWorker.weight_per_hour, 2) : '-' },
        { left: 'Min / hour', right: minWorker ? formatValue(minWorker.weight_per_hour, 2) : '-' },
      ],
    },
    {
      title: 'Unresolved Share',
      badge: formatPercent(overflowSummary.unresolved_quote || 0),
      color: '#6c757d',
      main: formatValue(overflowSummary.unresolved_weight_total || 0, 1),
      rows: [
        { left: 'Unresolved', right: formatValue(overflowSummary.unresolved_weight_total || 0, 1) },
        { left: 'Of overflow', right: formatPercent(overflowSummary.unresolved_quote || 0) },
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
  if (secondaryContainer) {
    secondaryContainer.innerHTML = renderCards(secondaryCards);
  }

  const strip = document.getElementById('signal-strip');
  if (strip) {
    const signals = [
      { label: 'Above band', value: `${bandStats.overBandWorkers.length}` },
      { label: 'Below band', value: `${bandStats.underBandWorkers.length}` },
      { label: 'Peak worker', value: maxWorker ? `${maxWorker.name} ${formatValue(maxWorker.weight_per_hour, 2)}` : '-' },
      { label: 'Top overflow', value: overflowSkills[0] ? `${overflowSkills[0].label} ${formatPercent(overflowSkills[0].overflowQuote)}` : '-' },
      { label: 'In band', value: `${bandStats.inBandCount}` },
    ];
    strip.innerHTML = signals.map(function(signal) {
      return `<div class="signal-pill"><span>${escapeHtml(signal.label)}</span><strong>${escapeHtml(signal.value)}</strong></div>`;
    }).join('');
  }
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
  const bandStats = computeBandStats(workerPayload);
  const skills = computeSkillMetrics(workers).slice(0, 5);
  const modalities = computeModalityMetrics(workers).slice(0, 5);
  const overflowSkills = getRequestedSkillOverflowMetrics(flowPayload)
    .sort(function(a, b) {
      if (b.overflowQuote !== a.overflowQuote) return b.overflowQuote - a.overflowQuote;
      return b.overflowWeight - a.overflowWeight;
    })
    .slice(0, 5);
  const overflowLinks = (flowPayload.links || [])
    .filter(function(link) { return Number(link.weight || 0) > 0; })
    .sort(function(a, b) { return Number(b.weight || 0) - Number(a.weight || 0); })
    .slice(0, 5);

  renderLeaderList('leaders-workers', [...bandStats.overBandWorkers.slice(0, 3), ...bandStats.underBandWorkers.slice(0, 2)], function(item) {
    return `${escapeHtml(item.name)}: <strong>${formatValue(item.weight_per_hour, 2)}</strong> /h`;
  });
  renderLeaderList('leaders-skills', skills, function(item) {
    return `${escapeHtml(item.label)}: <strong>${formatValue(item.weightPerHour, 2)}</strong> /h`;
  });
  renderLeaderList('leaders-modalities', modalities, function(item) {
    return `${escapeHtml(item.label)}: <strong>${formatValue(item.weightPerHour, 2)}</strong> /h`;
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
    renderOverviewCards(workerPayload, flowPayload);
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
});
