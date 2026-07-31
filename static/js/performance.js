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

function getSkillColor(skill) {
  return SKILL_SETTINGS[skill]?.button_color || '#5b7ea6';
}

function getModalityColor(modality) {
  return MODALITY_SETTINGS[modality]?.nav_color || '#6c757d';
}

function formatDailyLoadValue(value) {
  const numeric = Number(value || 0);
  return numeric.toFixed(numeric % 1 === 0 ? 0 : 1);
}

function minuteLabel(minute) {
  const numeric = Number(minute || 0);
  const hours = Math.floor(numeric / 60);
  const minutes = Math.floor(numeric % 60);
  return `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}`;
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

function renderOverviewCards(workerPayload, flowPayload, dailyLoadPayload, options = {}) {
  const primaryContainer = document.getElementById('summary-overview');
  if (!primaryContainer) return;

  const workers = workerPayload.workers || [];
  const workerDataAvailable = options.workerDataAvailable !== false;
  const flowDataAvailable = options.flowDataAvailable !== false;
  const totalWeight = workerDataAvailable
    ? workers.reduce(function(sum, worker) { return sum + Number(worker.global_weight || 0); }, 0)
    : null;
  const totalManualAdjustment = workerDataAvailable
    ? workers.reduce(function(sum, worker) { return sum + Number(worker.manual_adjustment || 0); }, 0)
    : null;
  const totalHours = workerDataAvailable
    ? workers.reduce(function(sum, worker) { return sum + Number(worker.hours_worked_now || 0); }, 0)
    : null;
  const globalPerHour = workerDataAvailable && totalHours > 0 ? totalWeight / totalHours : (workerDataAvailable ? 0 : null);
  const overflowSummary = flowPayload.summary || {};
  const dailyLoadAvailable = options.dailyLoadAvailable !== false;
  const requestInflow = dailyLoadAvailable
    ? Number(dailyLoadPayload?.total_weight || 0)
    : (flowDataAvailable ? Number(overflowSummary.total_inflow_weight || 0) : null);
  const recordedWorkers = workerDataAvailable ? workers.length : null;
  const overflowSupport = flowDataAvailable ? Number(overflowSummary.overflow_weight_total || 0) : null;
  const dataState = !workerDataAvailable || !flowDataAvailable || !dailyLoadAvailable
    ? 'Teildaten'
    : ((recordedWorkers > 0 || requestInflow > 0) ? 'Aktueller Tag' : 'Noch keine Daten');

  const primaryCards = [
    {
      title: 'Anfrage-Last',
      kicker: dataState,
      main: formatMaybeValue(requestInflow, 1),
      note: 'Summe der bisher eingegangenen Anforderungen, gewichtet nach Skill und Modalität.',
      className: 'summary-card-primary',
      rows: [
        { left: 'Bisher absorbierte Last', right: formatMaybeValue(totalWeight, 1) },
        { left: 'davon manuelle Anpassung', right: formatMaybeValue(totalManualAdjustment, 1) },
        { left: 'Overflow-Unterstützung', right: formatMaybeValue(overflowSupport, 1) },
      ],
    },
    {
      title: 'Globale Last / Stunde',
      kicker: 'Bis jetzt',
      main: formatMaybeValue(globalPerHour, 2),
      note: 'Absorbierte gewichtete Last geteilt durch die Summe der bisher aktiven Personenstunden.',
      className: 'summary-card-primary',
      rows: [
        { left: 'Summe aktiver Personenstunden', right: formatMaybeValue(totalHours, 1) },
        { left: 'Erfasste Mitarbeitende', right: recordedWorkers == null ? '—' : String(recordedWorkers) },
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
      ${card.note ? `<div class="summary-card-note">${escapeHtml(card.note)}</div>` : ''}
      ${card.rows.map(function(row) {
        return `<div class="summary-card-sub"><span>${escapeHtml(row.left)}</span><span>${escapeHtml(row.right)}</span></div>`;
      }).join('')}
    </div>`;
    }).join('');
  }

  primaryContainer.innerHTML = renderCards(primaryCards);
}

function renderLeaderList(id, items, formatter, emptyText = 'Noch keine Daten.') {
  const target = document.getElementById(id);
  if (!target) return;
  if (!items.length) {
    target.innerHTML = `<li>${escapeHtml(emptyText)}</li>`;
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

  renderLeaderList('leaders-skill-total', skills.sort(function(a, b) {
    return b.weightTotal - a.weightTotal;
  }).filter(function(item) {
    return Number(item.weightTotal || 0) > 0;
  }), function(item) {
    return `${escapeHtml(item.label)}: <strong>${formatValue(item.weightTotal, 1)}</strong> gewichtete Last <span style="color:#667;">(${formatValue(item.weightPerHour, 2)} /aktive h)</span>`;
  }, 'Noch keine absorbierte Last nach Skill.');
  renderLeaderList('leaders-modality-total', modalities.sort(function(a, b) {
    return b.weightTotal - a.weightTotal;
  }).filter(function(item) {
    return Number(item.weightTotal || 0) > 0;
  }), function(item) {
    return `${escapeHtml(item.label)}: <strong>${formatValue(item.weightTotal, 1)}</strong> gewichtete Last <span style="color:#667;">(${formatValue(item.weightPerHour, 2)} /aktive h)</span>`;
  }, 'Noch keine absorbierte Last nach Modalität.');
  renderLeaderList('leaders-overflow-skills', overflowSkills, function(item) {
    return `${escapeHtml(item.label)}: <strong>${formatPercent(item.overflowQuote)}</strong> Overflow (${formatValue(item.overflowWeight, 1)} von ${formatValue(item.inflowWeight, 1)} angefragter Last)`;
  }, 'Noch kein Skill-Overflow.');
  renderLeaderList('leaders-overflow', overflowLinks, function(item) {
    const from = flowPayload.skill_labels?.[item.from] || item.from;
    const to = flowPayload.skill_labels?.[item.to] || item.to;
    return `${escapeHtml(from)} → ${escapeHtml(to)}: <strong>${formatValue(item.weight, 1)}</strong> gewichtete Last`;
  }, 'Noch keine Overflow-Bewegungen.');
}

function renderDailyLoadChart(options, dailyLoadPayload) {
  const svg = document.getElementById(options.svgId);
  const legend = document.getElementById(options.legendId);
  const empty = document.getElementById(options.emptyId);
  const total = document.getElementById(options.totalId);
  if (!svg || !legend || !empty) return;

  const data = dailyLoadPayload || {};
  const meta = data.meta || {};
  const startMinute = Number(meta.start_minute || 420);
  const endMinute = Number(meta.end_minute || 1260);
  const rawSeries = Array.isArray(options.series) ? options.series : [];
  const series = [...rawSeries].sort(function(a, b) {
    return Number(a.total || 0) - Number(b.total || 0);
  });
  const maxY = Math.max(Number(data.max_y || 0), 1);
  const hasData = Number(data.event_count || 0) > 0 && rawSeries.some(function(item) {
    return Number(item.total || 0) > 0;
  });

  if (total) {
    total.textContent = `Gesamt ${formatDailyLoadValue(data.total_weight || 0)}`;
  }
  empty.style.display = hasData ? 'none' : 'block';

  const width = 760;
  const height = 310;
  const margin = { top: 18, right: 24, bottom: 38, left: 48 };
  const plotWidth = width - margin.left - margin.right;
  const plotHeight = height - margin.top - margin.bottom;
  const xForMinute = function(minute) {
    const clamped = Math.max(startMinute, Math.min(endMinute, Number(minute || startMinute)));
    return margin.left + ((clamped - startMinute) / Math.max(endMinute - startMinute, 1)) * plotWidth;
  };
  const yForValue = function(value) {
    return margin.top + plotHeight - ((Number(value || 0) / maxY) * plotHeight);
  };

  const hourTicks = [7, 9, 11, 13, 15, 17, 19, 21].map(function(hour) { return hour * 60; });
  const yTicks = [0, 0.25, 0.5, 0.75, 1].map(function(fraction) {
    return maxY * fraction;
  });

  const gridSvg = [
    `<rect x="0" y="0" width="${width}" height="${height}" fill="#fbfdff"></rect>`,
    ...hourTicks.map(function(minute) {
      const x = xForMinute(minute);
      return `<line x1="${x}" y1="${margin.top}" x2="${x}" y2="${margin.top + plotHeight}" stroke="#e5edf5" stroke-width="1"></line>
        <text x="${x}" y="${height - 13}" text-anchor="middle" font-size="10" fill="#5f6c77">${minuteLabel(minute).slice(0, 2)}</text>`;
    }),
    ...yTicks.map(function(value) {
      const y = yForValue(value);
      return `<line x1="${margin.left}" y1="${y}" x2="${margin.left + plotWidth}" y2="${y}" stroke="#e5edf5" stroke-width="1"></line>
        <text x="${margin.left - 9}" y="${y + 3}" text-anchor="end" font-size="10" fill="#5f6c77">${formatDailyLoadValue(value)}</text>`;
    }),
    `<line x1="${margin.left}" y1="${margin.top + plotHeight}" x2="${margin.left + plotWidth}" y2="${margin.top + plotHeight}" stroke="#b8c2d1" stroke-width="1.2"></line>`,
    `<line x1="${margin.left}" y1="${margin.top}" x2="${margin.left}" y2="${margin.top + plotHeight}" stroke="#b8c2d1" stroke-width="1.2"></line>`,
  ].join('');

  const lineSvg = hasData ? series.map(function(item) {
    const color = options.colorFor(item.key);
    const label = options.labelFor(item.key);
    const points = (item.points || []).map(function(point) {
      return `${xForMinute(point[0]).toFixed(1)},${yForValue(point[1]).toFixed(1)}`;
    }).join(' ');
    const active = Number(item.total || 0) > 0;
    return `<polyline points="${points}" fill="none" stroke="${color}" stroke-width="${active ? 2.4 : 1.2}" stroke-linejoin="round" stroke-linecap="round" opacity="${active ? 0.92 : 0.22}">
      <title>${escapeHtml(label)}: ${formatDailyLoadValue(item.total)}</title>
    </polyline>`;
  }).join('') : '';

  svg.setAttribute('viewBox', `0 0 ${width} ${height}`);
  svg.setAttribute('width', String(width));
  svg.setAttribute('height', String(height));
  svg.innerHTML = gridSvg + lineSvg;

  const legendSeries = hasData ? [...rawSeries].sort(function(a, b) {
    return Number(b.total || 0) - Number(a.total || 0);
  }).filter(function(item) {
    return Number(item.total || 0) > 0;
  }) : [];
  legend.innerHTML = legendSeries.map(function(item) {
    const color = options.colorFor(item.key);
    const label = options.labelFor(item.key);
    return `<span class="daily-load-legend-item" title="${escapeHtml(label)}">
      <span class="daily-load-legend-swatch" style="background:${color};opacity:${Number(item.total || 0) > 0 ? 1 : 0.35};"></span>
      <span>${escapeHtml(label)} ${formatDailyLoadValue(item.total)}</span>
    </span>`;
  }).join('');
}

function renderDailyLoadCharts(dailyLoadPayload) {
  renderDailyLoadChart({
    svgId: 'daily-load-skill-chart',
    legendId: 'daily-load-skill-legend',
    emptyId: 'daily-load-skill-empty',
    totalId: 'daily-load-skill-total',
    series: dailyLoadPayload.skill_series || [],
    labelFor: getSkillLabel,
    colorFor: getSkillColor,
  }, dailyLoadPayload);
  renderDailyLoadChart({
    svgId: 'daily-load-modality-chart',
    legendId: 'daily-load-modality-legend',
    emptyId: 'daily-load-modality-empty',
    totalId: 'daily-load-modality-total',
    series: dailyLoadPayload.modality_series || [],
    labelFor: getModalityLabel,
    colorFor: getModalityColor,
  }, dailyLoadPayload);
}

function loadSummaryData() {
  return Promise.allSettled([
    fetch('/api/worker-load/data').then(function(response) {
      if (!response.ok) throw new Error(`Worker-Last konnte nicht geladen werden (${response.status})`);
      return response.json();
    }),
    fetch('/api/performance/data').then(function(response) {
      if (!response.ok) throw new Error(`Flow-Daten konnten nicht geladen werden (${response.status})`);
      return response.json();
    }),
    fetch('/api/worker-load/daily-load').then(function(response) {
      if (!response.ok) throw new Error(`Tageslast konnte nicht geladen werden (${response.status})`);
      return response.json();
    }),
  ]).then(function(results) {
    const workerPayload = results[0].status === 'fulfilled' ? results[0].value : { workers: [], summary: {} };
    const flowPayload = results[1].status === 'fulfilled' ? results[1].value : { links: [], summary: {}, skill_labels: {} };
    const dailyLoadPayload = results[2].status === 'fulfilled'
      ? results[2].value
      : { skill_series: [], modality_series: [], event_count: 0, total_weight: 0, max_y: 0 };
    renderOverviewCards(workerPayload, flowPayload, dailyLoadPayload, {
      workerDataAvailable: results[0].status === 'fulfilled',
      flowDataAvailable: results[1].status === 'fulfilled',
      dailyLoadAvailable: results[2].status === 'fulfilled',
    });
    renderLeaderSections(workerPayload, flowPayload);
    renderDailyLoadCharts(dailyLoadPayload);
    if (results.every(function(result) { return result.status !== 'fulfilled'; })) {
      throw new Error('Analysis data could not be loaded.');
    }
  }).catch(function(error) {
    console.error('Analysis data could not be loaded:', error);
    const container = document.getElementById('summary-overview');
    if (container) {
      container.innerHTML = `<div class="summary-card-empty">${escapeHtml(error.message || 'Analysis data could not be loaded.')}</div>`;
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
