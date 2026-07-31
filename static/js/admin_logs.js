(function () {
  'use strict';

  const sources = JSON.parse(document.getElementById('admin-logs-config').textContent || '[]');
  const preview = document.getElementById('log-preview');
  const previewTitle = document.getElementById('preview-title');
  const previewMeta = document.getElementById('preview-meta');
  const refreshButton = document.getElementById('refresh-preview');
  const copyButton = document.getElementById('copy-preview');
  let activeSource = null;

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
    const link = event.currentTarget;
    if (link.getAttribute('aria-disabled') === 'true') event.preventDefault();
  }

  async function loadPreview(sourceKey) {
    const source = sources.find(item => item.key === sourceKey);
    if (!source) return;
    activeSource = sourceKey;
    const lines = Math.max(20, Math.min(1000, Number(document.getElementById('preview-lines').value) || 120));
    preview.textContent = 'Loading…';
    previewTitle.textContent = `${source.label} · tail`;
    previewMeta.textContent = source.path;
    refreshButton.disabled = true;
    copyButton.disabled = true;
    try {
      const response = await fetch(`/api/admin/logs/tail?source=${encodeURIComponent(sourceKey)}&lines=${lines}`, { cache: 'no-store' });
      const result = await response.json();
      if (!response.ok || !result.success) throw new Error(result.error || `Preview failed (${response.status})`);
      preview.textContent = result.exists ? (result.text || 'Log is empty.') : 'Log file does not exist.';
      previewMeta.textContent = `${result.path} · ${result.modified || 'unavailable'} · last ${lines} lines maximum`;
      copyButton.disabled = !result.text;
    } catch (error) {
      preview.textContent = error.message || 'Preview failed.';
    } finally {
      refreshButton.disabled = false;
    }
  }

  document.addEventListener('change', event => {
    if (event.target.matches('[data-source-check], #download-lines')) updateDownloadLinks();
  });
  document.addEventListener('click', event => {
    const button = event.target.closest('[data-preview-source]');
    if (button) loadPreview(button.dataset.previewSource);
  });
  refreshButton.addEventListener('click', () => { if (activeSource) loadPreview(activeSource); });
  copyButton.addEventListener('click', async () => {
    try {
      await navigator.clipboard.writeText(preview.textContent || '');
      copyButton.textContent = 'Copied';
      setTimeout(() => { copyButton.textContent = 'Copy'; }, 1200);
    } catch (_) {
      preview.focus();
    }
  });
  document.getElementById('preview-lines').addEventListener('change', () => { if (activeSource) loadPreview(activeSource); });
  document.getElementById('download-lines').addEventListener('input', updateDownloadLinks);
  document.getElementById('download-selected-tail').addEventListener('click', blockDisabledDownload);
  document.getElementById('download-selected-full').addEventListener('click', blockDisabledDownload);
  updateDownloadLinks();
  const firstExisting = sources.find(source => source.exists);
  if (firstExisting) loadPreview(firstExisting.key);
})();
