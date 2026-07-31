(function () {
  const AUTO_VALUE = '__auto__';
  let pending = null;
  let candidates = [];

  function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text == null ? '' : String(text);
    return div.innerHTML;
  }

  function getElements() {
    return {
      modal: document.getElementById('workerSelectModal'),
      context: document.getElementById('workerSelectContext'),
      select: document.getElementById('workerSelectChoice'),
      status: document.getElementById('workerSelectStatus'),
      confirmButton: document.getElementById('workerSelectConfirm'),
    };
  }

  function setStatus(message, type = '') {
    const { status } = getElements();
    if (!status) return;
    status.textContent = message || '';
    status.className = `worker-select-status ${type || ''}`.trim();
  }

  function skillLabel(skillSlug, fallbackLabel) {
    if (String(skillSlug || '').toLowerCase() === 'kinder') {
      return 'Kinderradiologie bis 16 Jahre';
    }
    return fallbackLabel || skillSlug || '';
  }

  function optionLabel(candidate) {
    const weighted = candidate.is_weighted ? ' · w' : '';
    // const load = candidate.ratio === null ? ' · Last: n/a' : ` · Last: ${candidate.ratio}`;
    const sourceSkillLabel = skillLabel(candidate.source_skill, candidate.source_skill_label);
    const source = candidate.source_modality_label
      ? ` · ${candidate.source_modality_label}/${sourceSkillLabel}`
      : '';
    return `${candidate.display_name}${weighted}${source}`;
  }

  function renderOptions() {
    const { select, confirmButton } = getElements();
    if (!select || !confirmButton) return;

    const autoLabel = pending?.autoLabel || 'Normal / automatisch';
    const autoOption = `<option value="${AUTO_VALUE}">${escapeHtml(autoLabel)}</option>`;
    const workerOptions = candidates.map(candidate => (
      `<option value="${escapeHtml(candidate.candidate_key)}">${escapeHtml(optionLabel(candidate))}</option>`
    )).join('');

    select.innerHTML = autoOption + workerOptions;
    confirmButton.disabled = false;
    if (!candidates.length) {
      setStatus('Keine manuellen Kandidaten verfuegbar. Normal nutzt die automatische strikte Zuweisung.');
      return;
    }
    setStatus(`${candidates.length} Kandidat(en) verfuegbar oder Normal automatisch nutzen.`);
  }

  async function open(options) {
    pending = options || {};
    candidates = [];
    const { modal, context, select, confirmButton } = getElements();
    if (!modal || !context || !select || !confirmButton) return;

    context.textContent = pending.contextText || 'Strikte Zuweisung';
    select.innerHTML = '<option value="">Lade Kandidaten...</option>';
    confirmButton.disabled = true;
    setStatus('');
    modal.classList.add('active');

    try {
      const data = await window.AssignmentUI.request(pending.candidatesUrl);
      candidates = data.candidates || [];
      renderOptions();
    } catch (error) {
      candidates = [];
      renderOptions();
      setStatus(window.AssignmentUI.message(error, { strict: true }), 'error');
    }
  }

  function close() {
    const { modal } = getElements();
    if (modal) modal.classList.remove('active');
    pending = null;
    candidates = [];
  }

  async function confirm() {
    if (!pending) return;
    const { select, confirmButton } = getElements();
    if (!select || !confirmButton) return;

    const value = select.value;
    if (!value) return;

    if (value === AUTO_VALUE) {
      const onAutoAssign = pending.onAutoAssign;
      close();
      if (typeof onAutoAssign === 'function') onAutoAssign();
      return;
    }

    try {
      confirmButton.disabled = true;
      setStatus('Zuweisung laeuft...');
      if (typeof pending.onManualStart === 'function') pending.onManualStart();
      const data = await window.AssignmentUI.request(pending.manualUrl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ candidate_key: value }),
      });
      const onManualSuccess = pending.onManualSuccess;
      close();
      if (typeof onManualSuccess === 'function') onManualSuccess(data);
    } catch (error) {
      setStatus(window.AssignmentUI.message(error, { strict: true }), 'error');
      if (typeof pending.onManualError === 'function') pending.onManualError(error);
    } finally {
      const elements = getElements();
      if (elements.confirmButton) elements.confirmButton.disabled = false;
    }
  }

  window.StrictWorkerSelect = {
    open,
    close,
    confirm,
    skillLabel,
  };

  document.addEventListener('keydown', event => {
    if (event.key === 'Escape') {
      close();
    }
  });
})();
