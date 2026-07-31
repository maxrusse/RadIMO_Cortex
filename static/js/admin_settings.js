(function () {
  'use strict';

  const initialSettings = JSON.parse(document.getElementById('admin-settings-config').textContent || '{}');
  const form = document.getElementById('general-settings-form');
  const message = document.getElementById('settings-message');
  const advanced = document.getElementById('advanced-config');
  const editor = document.getElementById('full-config-editor');
  const saveFullButton = document.getElementById('save-full-config');
  const acknowledgement = document.getElementById('advanced-config-ack');
  let yamlLoaded = false;

  function isEnglish() {
    return window.RadimoI18n?.language === 'en';
  }

  function showMessage(kind, text, details = '') {
    message.className = `message ${kind}`;
    message.textContent = text;
    if (details) {
      const detail = document.createElement('div');
      detail.style.cssText = 'font-weight:500;margin-top:.2rem;';
      detail.textContent = details;
      message.appendChild(detail);
    }
    message.focus({ preventScroll: true });
  }

  async function parseResponse(response) {
    const result = await response.json();
    if (!response.ok || !result.success) throw new Error(result.error || result.reload?.message || `Request failed (${response.status})`);
    return result;
  }

  function generalPayload() {
    const data = new FormData(form);
    return {
      default_language: data.get('default_language'),
      timezone: String(data.get('timezone') || '').trim(),
      worker_name_display_style: data.get('worker_name_display_style'),
      skill_roster_auto_import: data.has('skill_roster_auto_import'),
      access_protection_enabled: data.has('access_protection_enabled'),
      admin_access_protection_enabled: data.has('admin_access_protection_enabled')
    };
  }

  form.addEventListener('submit', async event => {
    event.preventDefault();
    const payload = generalPayload();
    if (initialSettings.admin_access_protection_enabled && !payload.admin_access_protection_enabled) {
      const accepted = confirm(isEnglish()
        ? 'Disable password protection for admin pages?'
        : 'Passwortschutz für Admin-Seiten deaktivieren?');
      if (!accepted) return;
    }
    const button = document.getElementById('save-general-settings');
    button.disabled = true;
    try {
      const result = await parseResponse(await fetch('/api/admin/config/general', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      }));
      const detail = [result.backup_path ? `Backup: ${result.backup_path}` : '', result.ready === false ? 'Readiness is not green.' : ''].filter(Boolean).join(' · ');
      showMessage(result.restart_required || result.ready === false ? 'warning' : 'success', 'Settings saved.', detail);
      Object.assign(initialSettings, payload);
    } catch (error) {
      showMessage('error', error.message || 'Settings could not be saved.');
    } finally {
      button.disabled = false;
    }
  });

  async function loadYaml(force = false) {
    if (yamlLoaded && !force) return;
    editor.disabled = true;
    editor.value = 'Loading…';
    saveFullButton.disabled = true;
    try {
      const response = await fetch('/api/admin/files/download?target=config', { cache: 'no-store' });
      if (!response.ok) throw new Error(`Download failed (${response.status})`);
      editor.value = await response.text();
      yamlLoaded = true;
      editor.disabled = false;
      saveFullButton.disabled = !acknowledgement.checked;
    } catch (error) {
      editor.value = '';
      showMessage('error', error.message || 'Configuration could not be loaded.');
    }
  }

  advanced.addEventListener('toggle', () => { if (advanced.open) loadYaml(); });
  acknowledgement.addEventListener('change', () => {
    saveFullButton.disabled = !yamlLoaded || !acknowledgement.checked || editor.disabled;
  });
  document.getElementById('reload-full-config').addEventListener('click', () => loadYaml(true));
  saveFullButton.addEventListener('click', async () => {
    if (!acknowledgement.checked || !yamlLoaded) return;
    const accepted = confirm(isEnglish()
      ? 'Validate, back up, and replace the complete active configuration?'
      : 'Vollständige aktive Konfiguration validieren, sichern und ersetzen?');
    if (!accepted) return;
    saveFullButton.disabled = true;
    try {
      const data = new FormData();
      data.set('target', 'config');
      data.set('file', new File([editor.value], 'config.yaml', { type: 'text/yaml' }));
      const result = await parseResponse(await fetch('/api/admin/files/upload', { method: 'POST', body: data }));
      const detail = result.backup_path ? `Backup: ${result.backup_path}` : '';
      showMessage(result.restart_required ? 'warning' : 'success', result.restart_required ? 'Configuration saved; service restart required.' : 'Configuration saved and reloaded.', detail);
      acknowledgement.checked = false;
    } catch (error) {
      showMessage('error', error.message || 'Configuration could not be saved.');
    } finally {
      saveFullButton.disabled = !acknowledgement.checked;
    }
  });
})();
