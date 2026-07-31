(function () {
  'use strict';

  let manifest = JSON.parse(document.getElementById('admin-files-config').textContent || '{}');
  let editorTarget = null;

  const grid = document.getElementById('managed-files-grid');
  const stagedContainer = document.getElementById('staged-days-content');
  const backupsContainer = document.getElementById('managed-backups-content');
  const messageContainer = document.getElementById('message-container');
  const editorModal = document.getElementById('managed-editor-modal');
  const editor = document.getElementById('managed-file-editor');

  function escapeHtml(value) {
    const div = document.createElement('div');
    div.textContent = value == null ? '' : String(value);
    return div.innerHTML;
  }

  function formatBytes(value) {
    const bytes = Number(value);
    if (!Number.isFinite(bytes)) return '—';
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }

  function translatedConfirm(en, de) {
    return confirm(window.RadimoI18n?.language === 'en' ? en : de);
  }

  function showMessage(kind, text, details = '') {
    messageContainer.innerHTML = `
      <div class="message ${escapeHtml(kind)}">
        ${escapeHtml(text)}${details ? `<div style="font-weight:500;margin-top:.2rem;">${escapeHtml(details)}</div>` : ''}
      </div>`;
    messageContainer.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  }

  function targetByKey(key) {
    return (manifest.targets || []).find(item => item.key === key);
  }

  function renderManagedFiles() {
    grid.innerHTML = (manifest.targets || []).map(entry => `
      <article class="managed-card" data-target-card="${escapeHtml(entry.key)}">
        <div class="card-head">
          <h2>${escapeHtml(entry.label)}</h2>
          <span class="badge ${entry.exists ? 'badge-ok' : 'badge-missing'}">${entry.exists ? 'present' : 'missing'}</span>
        </div>
        <code class="path">${escapeHtml(entry.path || entry.filename)}</code>
        <div class="meta-row">
          <span>${escapeHtml(entry.format || '')}</span>
          <span>${formatBytes(entry.size_bytes)}</span>
          <span>${escapeHtml(entry.modified || 'unavailable')}</span>
        </div>
        <div class="toolbar">
          <a class="btn btn-outline" href="${escapeHtml(entry.download_url)}">Download</a>
          ${entry.editable && entry.exists ? `<button class="btn btn-secondary" type="button" data-edit-target="${escapeHtml(entry.key)}">Edit in browser</button>` : ''}
          ${entry.exists ? `<button class="btn btn-secondary" type="button" data-reload-target="${escapeHtml(entry.key)}">Reload from disk</button>` : ''}
        </div>
        <details class="upload-panel">
          <summary>Upload replacement</summary>
          <form class="upload-form" data-upload-target="${escapeHtml(entry.key)}">
            <input type="file" name="file" required aria-label="Replacement file for ${escapeHtml(entry.label)}" accept="${entry.format === 'YAML' ? '.yaml,.yml,text/yaml' : '.json,application/json'}">
            <label class="ack"><input type="checkbox" name="ack" required aria-label="Confirm replacement of ${escapeHtml(entry.label)}"> I understand that this replaces the active ${escapeHtml(entry.label)} after validation and backup.</label>
            <button class="btn btn-primary" type="submit">Validate, back up &amp; apply</button>
          </form>
        </details>
      </article>
    `).join('');
  }

  function renderStagedDays() {
    const rows = (manifest.staged_days || []).map(entry => `
      <tr>
        <td><strong>${escapeHtml(entry.name)}</strong><br><code>${escapeHtml(entry.path)}</code></td>
        <td>${escapeHtml(entry.target_date)}${entry.is_current_target ? '<br><span class="badge badge-ok">current prep target</span>' : ''}</td>
        <td>${escapeHtml(entry.modified || '—')}<br>${formatBytes(entry.size_bytes)}</td>
        <td>${entry.is_canonical ? 'active file' : escapeHtml(entry.suffix || 'archive')}</td>
        <td><div class="toolbar">
          <a class="btn btn-outline" href="${escapeHtml(entry.download_url)}">Download</a>
          ${entry.is_canonical ? '' : `<button class="btn btn-secondary" type="button" data-restore-staged="${escapeHtml(entry.name)}">Restore as active</button>`}
        </div></td>
      </tr>`).join('');
    stagedContainer.innerHTML = `
      <form class="upload-form" data-upload-target="staged_day" style="grid-template-columns:minmax(150px,220px) minmax(220px,1fr) auto;align-items:end;margin-bottom:.55rem;">
        <label>Target date<input type="date" name="target_date" value="${escapeHtml(manifest.current_staged_target_date || '')}" required></label>
        <label>Unified staged snapshot JSON<input type="file" name="file" accept=".json,application/json" required></label>
        <div><label class="ack"><input type="checkbox" name="ack" required> Replace after validation and backup.</label><button class="btn btn-primary" type="submit">Upload staged day</button></div>
      </form>
      <div class="table-wrap"><table class="files-table">
        <thead><tr><th>File / path</th><th>Target day</th><th>Modified / size</th><th>Type</th><th>Actions</th></tr></thead>
        <tbody>${rows || '<tr><td colspan="5">No staged-day snapshots found.</td></tr>'}</tbody>
      </table></div>`;
  }

  function renderBackups() {
    const backupPaths = Object.values(manifest.backup_paths || {}).join(' · ');
    document.getElementById('backup-path-note').textContent = backupPaths || 'No backup directory available';
    const rows = (manifest.managed_backups || []).map(entry => `
      <tr>
        <td><strong>${escapeHtml(entry.name)}</strong><br><code>${escapeHtml(entry.path)}</code></td>
        <td>${escapeHtml(entry.target)}${entry.target_date ? ` · ${escapeHtml(entry.target_date)}` : ''}</td>
        <td>${escapeHtml(entry.modified || '—')}</td>
        <td>${formatBytes(entry.size_bytes)}</td>
        <td><div class="toolbar">
          <a class="btn btn-outline" href="${escapeHtml(entry.download_url)}">Download</a>
          <button class="btn btn-secondary" type="button" data-restore-backup="${escapeHtml(entry.name)}" data-backup-source="${escapeHtml(entry.source)}">Restore safely</button>
        </div></td>
      </tr>`).join('');
    backupsContainer.innerHTML = `
      <div class="table-wrap"><table class="files-table">
        <thead><tr><th>Backup / path</th><th>Restores</th><th>Modified</th><th>Size</th><th>Actions</th></tr></thead>
        <tbody>${rows || '<tr><td colspan="5">No managed backups found yet.</td></tr>'}</tbody>
      </table></div>`;
  }

  function renderPage() {
    renderManagedFiles();
    renderStagedDays();
    renderBackups();
  }

  async function parseResponse(response) {
    const result = await response.json();
    if (!response.ok || !result.success) {
      const error = new Error(result.error || result.reload?.message || `Request failed (${response.status})`);
      error.result = result;
      error.status = response.status;
      throw error;
    }
    return result;
  }

  function describeResult(result) {
    const parts = [];
    if (result.path) parts.push(`Active path: ${result.path}`);
    if (result.backup_path) parts.push(`Backup: ${result.backup_path}`);
    if (result.ready === false) parts.push('Readiness check is not green. Open Status.');
    return parts.join(' · ');
  }

  async function uploadForm(form) {
    const target = form.dataset.uploadTarget;
    const entry = targetByKey(target);
    const label = entry?.label || target;
    if (!translatedConfirm(
      `Validate, back up, and replace the active ${label}?`,
      `Aktive Datei „${label}“ validieren, sichern und ersetzen?`
    )) return;
    const button = form.querySelector('button[type="submit"]');
    button.disabled = true;
    try {
      const data = new FormData(form);
      data.set('target', target);
      const result = await parseResponse(await fetch('/api/admin/files/upload', { method: 'POST', body: data }));
      manifest = result.manifest || manifest;
      renderPage();
      const kind = result.restart_required ? 'warning' : 'success';
      const message = result.restart_required
        ? `${result.message}. Structural changes require a controlled service restart.`
        : (result.message || 'File replaced and runtime verified.');
      showMessage(kind, message, describeResult(result));
    } catch (error) {
      showMessage('error', error.message || 'Upload failed', 'The active file was not left partially written. Check Logs for details.');
    } finally {
      button.disabled = false;
    }
  }

  async function reloadTarget(target) {
    const entry = targetByKey(target);
    if (!translatedConfirm(
      `Reload ${entry?.label || target} from ${entry?.path || 'disk'} into the running application?`,
      `${entry?.label || target} von ${entry?.path || 'der Festplatte'} neu in die laufende Anwendung laden?`
    )) return;
    try {
      const response = await fetch('/api/admin/files/reload', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ target })
      });
      const result = await response.json();
      manifest = result.manifest || manifest;
      renderPage();
      if (!response.ok || !result.success) {
        showMessage(
          result.restart_required ? 'warning' : 'error',
          result.reload?.message || result.error || 'Reload failed',
          result.restart_required ? 'The running process remains on the previous structure; perform a controlled service restart.' : ''
        );
        return;
      }
      showMessage('success', result.message || 'Runtime reload complete.', describeResult(result));
    } catch (error) {
      showMessage('error', error.message || 'Reload failed');
    }
  }

  async function restoreStaged(name) {
    if (!translatedConfirm(
      `Restore ${name} as its active staged-day file? The current file is backed up first.`,
      `${name} als aktive Staging-Datei wiederherstellen? Die aktuelle Datei wird zuerst gesichert.`
    )) return;
    await restoreRequest({ target: 'staged_day', name });
  }

  async function restoreBackup(source, name) {
    if (!translatedConfirm(
      `Restore backup ${name}? The current active file is backed up again before restoration.`,
      `Backup ${name} wiederherstellen? Die aktuelle aktive Datei wird zuvor erneut gesichert.`
    )) return;
    await restoreRequest({ target: 'managed_backup', source, name });
  }

  async function restoreRequest(payload) {
    try {
      const result = await parseResponse(await fetch('/api/admin/files/restore', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload)
      }));
      manifest = result.manifest || manifest;
      renderPage();
      showMessage(result.restart_required ? 'warning' : 'success', result.message || 'Restore complete.', describeResult(result));
    } catch (error) {
      showMessage('error', error.message || 'Restore failed', 'The previous active file remains recoverable.');
    }
  }

  async function openEditor(target) {
    const entry = targetByKey(target);
    if (!entry?.editable) return;
    editorTarget = target;
    document.getElementById('managed-editor-title').textContent = `Edit ${entry.label}`;
    document.getElementById('managed-editor-meta').textContent = `${entry.format} · ${entry.path}`;
    editor.value = 'Loading…';
    editor.disabled = true;
    editorModal.classList.add('show');
    try {
      const response = await fetch(entry.download_url, { cache: 'no-store' });
      if (!response.ok) throw new Error(`Download failed (${response.status})`);
      editor.value = await response.text();
      editor.disabled = false;
      editor.focus();
      editor.setSelectionRange(0, 0);
    } catch (error) {
      closeEditor();
      showMessage('error', error.message || 'Could not open editor');
    }
  }

  function closeEditor() {
    editorModal.classList.remove('show');
    editor.disabled = false;
    editorTarget = null;
  }

  async function saveEditor() {
    const target = editorTarget;
    const entry = targetByKey(target);
    if (!entry) return;
    if (entry.format === 'JSON') {
      try { JSON.parse(editor.value); }
      catch (error) {
        showMessage('error', `JSON validation failed: ${error.message}`);
        editor.focus();
        return;
      }
    }
    if (!translatedConfirm(
      `Validate, back up, and apply the edited ${entry.label}?`,
      `Bearbeitete Datei „${entry.label}“ validieren, sichern und anwenden?`
    )) return;
    const button = document.getElementById('managed-editor-save');
    button.disabled = true;
    try {
      const data = new FormData();
      data.set('target', target);
      data.set('file', new File([editor.value], entry.filename, { type: entry.format === 'JSON' ? 'application/json' : 'text/yaml' }));
      const result = await parseResponse(await fetch('/api/admin/files/upload', { method: 'POST', body: data }));
      manifest = result.manifest || manifest;
      closeEditor();
      renderPage();
      showMessage(result.restart_required ? 'warning' : 'success', result.message, describeResult(result));
    } catch (error) {
      showMessage('error', error.message || 'Save failed', 'The editor remains open; the active file was not partially written.');
      editor.focus();
    } finally {
      button.disabled = false;
    }
  }

  async function refreshManifest() {
    const button = document.getElementById('refresh-manifest-btn');
    button.disabled = true;
    try {
      const result = await parseResponse(await fetch('/api/admin/files/manifest', { cache: 'no-store' }));
      manifest = result.manifest;
      renderPage();
      showMessage('success', 'File paths, metadata, and backups refreshed.');
    } catch (error) {
      showMessage('error', error.message || 'Refresh failed');
    } finally {
      button.disabled = false;
    }
  }

  document.addEventListener('submit', event => {
    const form = event.target.closest('form[data-upload-target]');
    if (!form) return;
    event.preventDefault();
    uploadForm(form);
  });

  document.addEventListener('click', event => {
    const editButton = event.target.closest('[data-edit-target]');
    const reloadButton = event.target.closest('[data-reload-target]');
    const stagedButton = event.target.closest('[data-restore-staged]');
    const backupButton = event.target.closest('[data-restore-backup]');
    if (editButton) openEditor(editButton.dataset.editTarget);
    else if (reloadButton) reloadTarget(reloadButton.dataset.reloadTarget);
    else if (stagedButton) restoreStaged(stagedButton.dataset.restoreStaged);
    else if (backupButton) restoreBackup(backupButton.dataset.backupSource, backupButton.dataset.restoreBackup);
  });

  document.getElementById('managed-editor-cancel').addEventListener('click', closeEditor);
  document.getElementById('managed-editor-save').addEventListener('click', saveEditor);
  document.getElementById('refresh-manifest-btn').addEventListener('click', refreshManifest);
  editor.addEventListener('keydown', event => {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's') {
      event.preventDefault();
      saveEditor();
    }
  });

  renderPage();
})();
