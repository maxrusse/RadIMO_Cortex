// Coverage helpers for the Today / Planning editor:
// - coverage gaps (skill × modality combinations without an active worker)
// - coverage over the day (active workers per skill along the timeline)
// - prepared planning days and ?date= deep links

function isAssignedModality(modData) {
  return Boolean(modData) && modData.row_index !== undefined && modData.row_index >= 0;
}

function countActiveBySkillAndModality(groups) {
  const counts = {};
  SKILLS.forEach(skill => {
    counts[skill] = {};
    MODALITIES.forEach(mod => { counts[skill][mod.toLowerCase()] = 0; });
  });
  (groups || []).forEach(group => {
    const shifts = getTableShifts(group).filter(shift => !shift.deleted && !shift.is_gap_entry);
    SKILLS.forEach(skill => {
      MODALITIES.forEach(mod => {
        const modKey = mod.toLowerCase();
        const active = shifts.some(shift => {
          const modData = shift.modalities[modKey];
          return isAssignedModality(modData) && isActiveSkillValue(modData.skills[skill]);
        });
        if (active) counts[skill][modKey] += 1;
      });
    });
  });
  return counts;
}

// Plain warning line: which modality × skill combinations nobody covers (1 or w) on this day.
function renderCoverageGaps(tab) {
  const container = document.getElementById(`coverage-gaps-${tab}`);
  if (!container) return;
  const groups = entriesData[tab] || [];
  if (!groups.length) {
    container.innerHTML = '';
    return;
  }
  const counts = countActiveBySkillAndModality(groups);
  const parts = [];
  MODALITIES.forEach(mod => {
    const modKey = mod.toLowerCase();
    const missing = SKILLS.filter(skill => counts[skill][modKey] === 0);
    if (!missing.length) return;
    const modLabel = (MODALITY_SETTINGS[modKey]?.label || mod).toUpperCase();
    parts.push(`<span class="prep-coverage__group"><span class="prep-coverage__mod" style="--mod-color:${getModalityColor(modKey)}">${escapeHtml(modLabel)}</span> ${escapeHtml(missing.join(', '))}</span>`);
  });
  if (!parts.length) {
    container.innerHTML = '';
    return;
  }
  const label = window.RadimoUI.text('Nobody with 1 or w on this day for:', 'An diesem Tag niemand mit 1 oder w für:');
  container.innerHTML = `<span class="prep-coverage__label">⚠ ${escapeHtml(label)}</span>${parts.join('<span class="prep-coverage__sep">·</span>')}`;
}

function renderCoverageStrip(tab) {
  const container = document.getElementById(`coverage-strip-${tab}`);
  if (!container || typeof TimelineChart === 'undefined') return;
  const groups = entriesData[tab] || [];
  if (!groups.length) {
    container.innerHTML = '';
    return;
  }
  const t = text => window.RadimoI18n?.t(text) || text;
  const startMin = TimelineChart.TIMELINE_START * 60;
  const endMin = TimelineChart.TIMELINE_END * 60;
  const step = 15;
  const toMinutes = value => {
    const [h, m] = String(value || '').split(':').map(Number);
    return Number.isFinite(h) ? h * 60 + (Number.isFinite(m) ? m : 0) : null;
  };

  // Active intervals per skill per worker (shift segments only; gaps are separate rows)
  const intervalsBySkill = {};
  SKILLS.forEach(skill => { intervalsBySkill[skill] = {}; });
  groups.forEach(group => {
    getTableShifts(group).filter(shift => !shift.deleted && !shift.is_gap_entry).forEach(shift => {
      const start = toMinutes(shift.start_time);
      const end = toMinutes(shift.end_time);
      if (start === null || end === null || end <= start) return;
      SKILLS.forEach(skill => {
        const active = Object.values(shift.modalities || {}).some(modData =>
          isAssignedModality(modData) && isActiveSkillValue(modData.skills[skill]));
        if (!active) return;
        (intervalsBySkill[skill][group.worker] ||= []).push([start, end]);
      });
    });
  });

  // Only flag "nobody" inside the staffed day (first shift start to last shift end).
  let dayStart = endMin;
  let dayEnd = startMin;
  SKILLS.forEach(skill => Object.values(intervalsBySkill[skill]).forEach(intervals => intervals.forEach(([s, e]) => {
    dayStart = Math.min(dayStart, s);
    dayEnd = Math.max(dayEnd, e);
  })));
  groups.forEach(group => getTableShifts(group).filter(shift => !shift.deleted && !shift.is_gap_entry).forEach(shift => {
    const s = toMinutes(shift.start_time);
    const e = toMinutes(shift.end_time);
    if (s !== null && e !== null && e > s) {
      dayStart = Math.min(dayStart, s);
      dayEnd = Math.max(dayEnd, e);
    }
  }));

  const span = endMin - startMin;
  const rows = SKILLS.map(skill => {
    const color = SKILL_SETTINGS[skill]?.button_color || '#6c757d';
    const segments = [];
    for (let minute = startMin; minute < endMin; minute += step) {
      const mid = minute + step / 2;
      let count = 0;
      Object.values(intervalsBySkill[skill]).forEach(intervals => {
        if (intervals.some(([s, e]) => mid >= s && mid < e)) count += 1;
      });
      const last = segments[segments.length - 1];
      if (last && last.count === count) last.end = minute + step;
      else segments.push({ start: minute, end: minute + step, count });
    }
    const maxCount = Math.max(1, ...segments.map(seg => seg.count));
    const segHtml = segments.map(seg => {
      const left = ((seg.start - startMin) / span) * 100;
      const width = ((seg.end - seg.start) / span) * 100;
      const fmt = m => `${String(Math.floor(m / 60)).padStart(2, '0')}:${String(m % 60).padStart(2, '0')}`;
      const title = `${skill} ${fmt(seg.start)}–${fmt(seg.end)}: ${seg.count}`;
      if (seg.count === 0) {
        if (seg.end <= dayStart || seg.start >= dayEnd) return '';
        return `<div class="coverage-seg coverage-seg--zero" style="left:${left}%;width:${width}%" title="${escapeHtml(title)}"></div>`;
      }
      const opacity = 0.45 + 0.55 * (seg.count / maxCount);
      return `<div class="coverage-seg" style="left:${left}%;width:${width}%;background:${color};opacity:${opacity.toFixed(2)}" title="${escapeHtml(title)}">${width > 2.5 ? seg.count : ''}</div>`;
    }).join('');
    return `<div class="coverage-row"><div class="coverage-row__label" title="${escapeHtml(skill)}">${escapeHtml(skill)}</div><div class="coverage-row__track">${segHtml}</div></div>`;
  }).join('');

  container.innerHTML = `<div class="coverage-strip__title">${escapeHtml(t('Coverage over the day'))} <span>· ${escapeHtml(t('1 or w, all modalities · hatched = nobody'))}</span></div>${rows}`;
}

async function renderPreparedDays() {
  const container = document.getElementById('prep-staged-days');
  if (!container) return;
  const t = text => window.RadimoI18n?.t(text) || text;
  try {
    const response = await fetch('/api/admin/files/manifest');
    if (!response.ok) return;
    const payload = await response.json();
    const manifest = payload.manifest || payload;
    const dates = [...new Set((manifest.staged_days || [])
      .filter(entry => entry.is_canonical && entry.target_date && (!prepMinDate || entry.target_date >= prepMinDate))
      .map(entry => entry.target_date))].sort().slice(0, 8);
    if (!dates.length) {
      container.innerHTML = '';
      return;
    }
    const chips = dates.map(dateValue => {
      const dateObj = new Date(`${dateValue}T00:00:00`);
      const label = dateObj.toLocaleDateString('de-DE', { weekday: 'short', day: '2-digit', month: '2-digit' });
      const active = dateValue === prepTargetDate;
      return `<button type="button" class="ui-chip${active ? ' is-active' : ''}" data-staged-date="${dateValue}" title="${escapeHtml(t('Open prepared day'))}">${escapeHtml(label)}</button>`;
    }).join('');
    container.innerHTML = `<span class="prep-staged-days__label">${escapeHtml(t('Prepared:'))}</span>${chips}`;
  } catch (error) {
    console.warn('Prepared days unavailable:', error);
  }
}

function openPlanningDate(dateValue) {
  const inputEl = document.getElementById('prep-target-date');
  if (!inputEl || !dateValue || dateValue === prepTargetDate) return;
  inputEl.value = dateValue;
  onPrepDateInputChange();
}

document.addEventListener('click', event => {
  const chip = event.target.closest('[data-staged-date]');
  if (chip) openPlanningDate(chip.dataset.stagedDate);
});

function updatePreparedDayChips() {
  document.querySelectorAll('[data-staged-date]').forEach(chip => {
    chip.classList.toggle('is-active', chip.dataset.stagedDate === prepTargetDate);
  });
}
