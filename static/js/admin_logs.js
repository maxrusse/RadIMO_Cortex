(function () {
  'use strict';

  const sources = JSON.parse(document.getElementById('admin-logs-config').textContent || '[]');
  const preview = document.getElementById('log-preview');
  const previewMeta = document.getElementById('preview-meta');
  const previewCount = document.getElementById('preview-count');
  const sourceSelect = document.getElementById('preview-source');
  const refreshButton = document.getElementById('refresh-preview');
  const copyButton = document.getElementById('copy-preview');
  const params = new URLSearchParams(window.location.search);
  let level = ['error', 'warning'].includes(params.get('level')) ? params.get('level') : '';
  let activeSource = null;
  let lastText = '';

  function t(text) {
    return window.RadimoI18n?.t ? window.RadimoI18n.t(text) : text;
  }

  function selectedSources() {
    return Array.from(document.querySelectorAll('[data-source-check]:checked')).map(input => input.dataset.sourceCheck);
  }

  function updateDownloadLinks() {
    const selected = selectedSources();
    const sourceParam = encodeURIComponent(selected.join(','));
    const lines = Math.max(1, Math.min(50000, Number(document.getElementById('download-lines').value) || 5000));
    const tailLink = document.getElementById('download-selected-tail');
    const fullLink = document.getElementById('download-selected-full');
    tailLink.href = `/admin/logs/download?sources=${sourceParam}&scope=tail&lines=${lines}`;
    fullLink.href = `/admin/logs/download?sources=${sourceParam}&scope=full`;
    tailLink.setAttribute('aria-disabled', selected.length ? 'false' : 'true');
    fullLink.setAttribute('aria-disabled', selected.length ? 'false' : 'true');
  }

  function blockDisabledDownload(event) {
    if (event.currentTarget.getAttribute('aria-disabled') === 'true') event.preventDefault();
  }

  function lineLevel(line) {
    if (/\[(ERROR|CRITICAL)\]|Traceback/.test(line)) return 'error';
    if (/\[WARNING\]/.test(line)) return 'warning';
    return '';
  }

  function renderPreview() {
    preview.textContent = '';
    if (!lastText) return;
    const lines = lastText.split('\n');
    let shown = 0;
    let errors = 0;
    let warnings = 0;
    const fragment = document.createDocumentFragment();
    lines.forEach(line => {
      const lineKind = lineLevel(line);
      if (lineKind === 'error') errors += 1;
      if (lineKind === 'warning') warnings += 1;
      const visible = !level || lineKind === 'error' || (level === 'warning' && lineKind === 'warning');
      const span = document.createElement('span');
      span.className = `log-line${lineKind ? ` log-line--${lineKind}` : ''}${visible ? '' : ' log-line--hidden'}`;
      span.textContent = line + '\n';
      if (visible) shown += 1;
      fragment.appendChild(span);
    });
    preview.appendChild(fragment);
    previewCount.textContent = `${shown} / ${lines.length} ${t('lines')} · ${errors} ${t('errors')} · ${warnings} ${t('warnings')}`;
    if (level && !shown) preview.textContent = t('No matching lines in this window.');
    preview.scrollTop = preview.scrollHeight;
  }

  function setLevel(nextLevel) {
    level = nextLevel;
    document.querySelectorAll('[data-level]').forEach(button => {
      button.setAttribute('aria-pressed', button.dataset.level === level ? 'true' : 'false');
    });
    const url = new URL(window.location.href);
    if (level) url.searchParams.set('level', level);
    else url.searchParams.delete('level');
    window.history.replaceState(null, '', url);
    renderPreview();
  }

  async function loadPreview(sourceKey) {
    const source = sources.find(item => item.key === sourceKey);
    if (!source) return;
    activeSource = sourceKey;
    sourceSelect.value = sourceKey;
    const lines = Math.max(20, Math.min(1000, Number(document.getElementById('preview-lines').value) || 300));
    preview.textContent = t('Loading...');
    previewMeta.textContent = source.path;
    refreshButton.disabled = true;
    copyButton.disabled = true;
    try {
      const response = await fetch(`/api/admin/logs/tail?source=${encodeURIComponent(sourceKey)}&lines=${lines}`, { cache: 'no-store' });
      const result = await response.json();
      if (!response.ok || !result.success) throw new Error(result.error || `Preview failed (${response.status})`);
      if (!result.exists) {
        lastText = '';
        preview.textContent = t('Log file does not exist.');
        previewCount.textContent = '';
      } else {
        lastText = result.text || '';
        if (!lastText) preview.textContent = t('Log is empty.');
        renderPreview();
      }
      previewMeta.textContent = `${result.path} · ${result.modified || 'unavailable'} · last ${lines} lines maximum`;
      copyButton.disabled = !lastText;
    } catch (error) {
      preview.textContent = error.message || 'Preview failed.';
    } finally {
      refreshButton.disabled = false;
    }
  }

  document.addEventListener('change', event => {
    if (event.target.matches('[data-source-check], #download-lines')) updateDownloadLinks();
  });
  document.querySelectorAll('[data-level]').forEach(button => {
    button.addEventListener('click', () => setLevel(button.dataset.level));
  });
  sourceSelect.addEventListener('change', () => loadPreview(sourceSelect.value));
  refreshButton.addEventListener('click', () => { if (activeSource) loadPreview(activeSource); });
  copyButton.addEventListener('click', async () => {
    try {
      const visible = Array.from(preview.querySelectorAll('.log-line:not(.log-line--hidden)')).map(line => line.textContent).join('');
      await navigator.clipboard.writeText(visible || lastText);
      copyButton.textContent = t('Copied');
      setTimeout(() => { copyButton.textContent = t('Copy'); }, 1200);
    } catch (_) {
      preview.focus();
    }
  });
  document.getElementById('preview-lines').addEventListener('change', () => { if (activeSource) loadPreview(activeSource); });
  document.getElementById('download-lines').addEventListener('input', updateDownloadLinks);
  document.getElementById('download-selected-tail').addEventListener('click', blockDisabledDownload);
  document.getElementById('download-selected-full').addEventListener('click', blockDisabledDownload);
  updateDownloadLinks();
  setLevel(level);
  const preferred = sources.find(source => source.key === 'selection' && source.exists) || sources.find(source => source.exists);
  if (preferred) loadPreview(preferred.key);
})();
