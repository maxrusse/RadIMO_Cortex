let manualWorkers = [];
let manualDeltas = [];
let manualLog = [];
let selectedManualWorker = null;

function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text == null ? '' : String(text);
  return div.innerHTML;
}

function formatWeight(value, digits = 2) {
  return Number(value || 0).toFixed(digits);
}

function formatDelta(value) {
  const numberValue = Number(value || 0);
  const prefix = numberValue > 0 ? '+' : '';
  return `${prefix}${formatWeight(numberValue)}`;
}

function deltaClass(value) {
  const numberValue = Number(value || 0);
  if (numberValue > 0) return 'ma-positive';
  if (numberValue < 0) return 'ma-negative';
  return '';
}

function formatTimestamp(value) {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

function setStatus(message, type = '') {
  const status = document.getElementById('manual-adjustment-status');
  if (!status) return;
  status.textContent = message || '';
  status.className = `status ${type || ''}`.trim();
}

function setModalStatus(message, type = '') {
  const status = document.getElementById('manual-modal-status');
  if (!status) return;
  status.textContent = message || '';
  status.className = `status ${type || ''}`.trim();
}

async function fetchManualAdjustmentData() {
  const response = await fetch('/api/manual-adjustments');
  const payload = await response.json();
  if (!response.ok || !payload.success) {
    throw new Error(payload.error || 'Failed to load manual adjustments');
  }
  manualWorkers = payload.workers || [];
  manualDeltas = payload.allowed_deltas || [];
  manualLog = payload.adjustments || [];
}

function renderWorkers() {
  const tbody = document.getElementById('manual-worker-body');
  if (!tbody) return;
  if (!manualWorkers.length) {
    tbody.innerHTML = '<tr><td colspan="6">No active workers found.</td></tr>';
    return;
  }

  const query = (document.getElementById('manual-worker-filter')?.value || '').trim().toLocaleLowerCase();
  const adjustedOnly = Boolean(document.getElementById('manual-adjusted-only')?.checked);
  const visibleWorkers = manualWorkers.filter(worker => {
    const matchesQuery = !query || `${worker.name || ''} ${worker.canonical_id || ''}`.toLocaleLowerCase().includes(query);
    const hasCorrection = Number(worker.manual_adjustment || 0) !== 0;
    return matchesQuery && (!adjustedOnly || hasCorrection);
  });
  const count = document.getElementById('manual-filter-count');
  if (count) {
    count.textContent = window.RadimoI18n?.language === 'en'
      ? `${visibleWorkers.length} of ${manualWorkers.length}`
      : `${visibleWorkers.length} von ${manualWorkers.length}`;
  }
  if (!visibleWorkers.length) {
    tbody.innerHTML = '<tr><td colspan="6">No workers match the filter.</td></tr>';
    return;
  }

  tbody.innerHTML = visibleWorkers.map(worker => {
    const ma = Number(worker.manual_adjustment || 0);
    const encodedWorkerId = encodeURIComponent(worker.canonical_id || '');
    return `<tr>
      <td>${escapeHtml(worker.name)}</td>
      <td class="num">${formatWeight(worker.hours_worked_now)}</td>
      <td class="num">${formatWeight(worker.balance_weight)}</td>
      <td class="num ${deltaClass(ma)}">${formatDelta(ma)}</td>
      <td class="num">${formatWeight(worker.total_weight)}</td>
      <td><button type="button" class="btn btn-primary" onclick="openManualAdjustmentModalByEncoded('${encodedWorkerId}')">Manual adjust</button></td>
    </tr>`;
  }).join('');
}

function renderLog() {
  const tbody = document.getElementById('manual-log-body');
  if (!tbody) return;
  if (!manualLog.length) {
    tbody.innerHTML = '<tr><td colspan="8">No manual adjustments published today.</td></tr>';
    return;
  }

  tbody.innerHTML = manualLog.map(entry => {
    const delta = Number(entry.delta || 0);
    return `<tr>
      <td>${escapeHtml(formatTimestamp(entry.timestamp))}</td>
      <td>${escapeHtml(entry.admin_name)}</td>
      <td>${escapeHtml(entry.client_ip || '')}</td>
      <td>${escapeHtml(entry.worker_name || entry.worker_id)}</td>
      <td class="num ${deltaClass(delta)}">${formatDelta(delta)}</td>
      <td class="num">${formatWeight(entry.balance_before)}</td>
      <td class="num">${formatWeight(entry.total_after)}</td>
      <td>${escapeHtml(entry.reason)}</td>
    </tr>`;
  }).join('');
}

function renderDeltaOptions() {
  const select = document.getElementById('manual-delta');
  if (!select) return;
  const uniqueSortedDeltas = Array.from(new Set(
    manualDeltas.map(delta => Number(delta)).filter(delta => Number.isFinite(delta))
  )).sort((a, b) => a - b);
  select.innerHTML = uniqueSortedDeltas.map(delta => (
    `<option value="${Number(delta)}">${escapeHtml(formatDelta(delta))}</option>`
  )).join('');
  const plusOneOption = Array.from(select.options).find(option => Number(option.value) === 1);
  if (plusOneOption) {
    select.value = plusOneOption.value;
  }
}

function openManualAdjustmentModal(workerId) {
  selectedManualWorker = manualWorkers.find(worker => worker.canonical_id === workerId);
  if (!selectedManualWorker) return;
  renderDeltaOptions();
  document.getElementById('manual-worker-name').value = selectedManualWorker.name;
  document.getElementById('manual-admin-name').value = '';
  document.getElementById('manual-reason').value = '';
  document.getElementById('manual-admin-password').value = '';
  document.getElementById('manual-adjustment-modal').classList.add('show');
  setModalStatus('');
}

function openManualAdjustmentModalByEncoded(workerId) {
  openManualAdjustmentModal(decodeURIComponent(workerId || ''));
}

function closeManualAdjustmentModal() {
  selectedManualWorker = null;
  document.getElementById('manual-adjustment-modal').classList.remove('show');
}

async function submitManualAdjustment() {
  if (!selectedManualWorker) return;
  const submitButton = document.getElementById('manual-submit-button');
  const payload = {
    worker_id: selectedManualWorker.canonical_id,
    delta: Number(document.getElementById('manual-delta').value),
    admin_name: document.getElementById('manual-admin-name').value.trim(),
    reason: document.getElementById('manual-reason').value.trim(),
    admin_password: document.getElementById('manual-admin-password').value,
  };
  const requiredFields = [
    ['manual-reason', payload.reason],
    ['manual-admin-name', payload.admin_name],
    ['manual-admin-password', payload.admin_password],
  ];
  const missing = requiredFields.find(([, value]) => !value);
  if (missing) {
    setModalStatus(
      window.RadimoI18n?.language === 'en' ? 'Please complete all required fields.' : 'Bitte alle Pflichtfelder ausfüllen.',
      'error'
    );
    document.getElementById(missing[0])?.focus();
    return;
  }

  try {
    if (submitButton) submitButton.disabled = true;
    const response = await fetch('/api/manual-adjustments', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const result = await response.json();
    if (!response.ok || !result.success) {
      throw new Error(result.error || 'Manual adjustment failed');
    }
    manualWorkers = result.workers || [];
    manualLog = result.adjustments || [];
    renderWorkers();
    renderLog();
    closeManualAdjustmentModal();
    setStatus('Manual adjustment published.', 'success');
    setModalStatus('');
  } catch (error) {
    setModalStatus(error.message, 'error');
    document.getElementById('manual-admin-password')?.focus();
  } finally {
    if (submitButton) submitButton.disabled = false;
  }
}

async function initializeManualAdjustments() {
  try {
    await fetchManualAdjustmentData();
    renderWorkers();
    renderLog();
    setStatus('');
  } catch (error) {
    setStatus(error.message, 'error');
  }
}

document.addEventListener('DOMContentLoaded', initializeManualAdjustments);
document.addEventListener('DOMContentLoaded', () => {
  document.getElementById('manual-worker-filter')?.addEventListener('input', renderWorkers);
  document.getElementById('manual-adjusted-only')?.addEventListener('change', renderWorkers);
});
document.addEventListener('radimo:languagechange', renderWorkers);
document.addEventListener('keydown', event => {
  if (event.key === 'Escape') {
    closeManualAdjustmentModal();
  }
});
