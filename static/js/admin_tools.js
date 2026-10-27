// Log signal: count ERROR / WARNING lines in the tail of each log source.
(function () {
  'use strict';

  const target = document.getElementById('logSignal');
  const sourcesEl = document.getElementById('log-sources');
  if (!target || !sourcesEl) return;
  const t = text => (window.RadimoI18n?.t ? window.RadimoI18n.t(text) : text);
  const sources = JSON.parse(sourcesEl.textContent || '[]');

  Promise.all(sources.map(source => fetch(`/api/admin/logs/tail?source=${encodeURIComponent(source)}&lines=500`, { cache: 'no-store' })
    .then(response => response.json())
    .catch(() => null)))
    .then(results => {
      let errors = 0;
      let warnings = 0;
      let missing = 0;
      results.forEach(result => {
        if (!result || !result.success) return;
        if (!result.exists) { missing += 1; return; }
        (result.text || '').split('\n').forEach(line => {
          if (/\[(ERROR|CRITICAL)\]/.test(line)) errors += 1;
          else if (/\[WARNING\]/.test(line)) warnings += 1;
        });
      });
      const parts = [
        `<strong class="${errors ? 'is-error' : 'is-ok'}">${errors}</strong> ${t('errors')}`,
        `<strong class="${warnings ? 'is-warn' : 'is-ok'}">${warnings}</strong> ${t('warnings')}`,
      ];
      if (missing) parts.push(`${missing} ${t('sources missing')}`);
      const link = errors || warnings
        ? ` <a class="ui-btn ui-btn--secondary ui-btn--sm" href="/admin/logs?level=${errors ? 'error' : 'warning'}">${t('Show in Logs')}</a>`
        : '';
      target.innerHTML = parts.join(' · ') + link;
    });
})();

(function () {
  'use strict';

  const button = document.getElementById('runtime-reload');
  const message = document.getElementById('runtime-message');
  if (!button || !message) return;

  function isEnglish() {
    return window.RadimoI18n?.language === 'en';
  }

  function show(kind, text) {
    message.textContent = '';
    if (text) window.RadimoUI.notify(kind || 'info', text);
  }

  button.addEventListener('click', async () => {
    const accepted = confirm(isEnglish()
      ? 'Reload the RadIMO application now? Active requests can finish; Gunicorn starts fresh workers.'
      : 'RadIMO-Anwendung jetzt neu laden? Laufende Anfragen können beendet werden; Gunicorn startet frische Worker.');
    if (!accepted) return;

    button.disabled = true;
    show('', isEnglish() ? 'Requesting reload…' : 'Neuladen wird angefordert…');
    try {
      const response = await fetch('/api/admin/runtime/reload', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ confirmation: 'reload' })
      });
      const result = await response.json();
      if (!response.ok || !result.success) throw new Error(result.error || `Request failed (${response.status})`);
      show('success', isEnglish()
        ? 'Reload requested. The application remains available.'
        : 'Neuladen angefordert. Die Anwendung bleibt erreichbar.');
    } catch (error) {
      show('error', error.message || (isEnglish() ? 'Reload failed.' : 'Neuladen fehlgeschlagen.'));
    } finally {
      button.disabled = false;
    }
  });
})();
